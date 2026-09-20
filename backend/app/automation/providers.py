"""Provider adapters; no retry of uncertain mutations, no credential logging."""

import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx


class UnknownEffect(Exception):
    pass


class ProviderError(Exception):
    def __init__(self, message, status=None, *, retry_after=0, category=None, retryable=None):
        super().__init__(message)
        self.status = status
        self.category = category or (
            "credits"
            if status == 402
            else "authentication"
            if status in {401, 403}
            else "rate_limit"
            if status == 429
            else "unavailable"
            if status is None or status >= 500
            else "rejected"
        )
        self.retryable = (
            retryable
            if retryable is not None
            else (status is None or status in {408, 425, 429} or status >= 500)
        )
        self.retry_after = retry_after


def retry_delay(value):
    try:
        return max(0, min(86400, float(value)))
    except (ValueError, TypeError):
        try:
            return max(0, min(86400, parsedate_to_datetime(value).timestamp() - time.time()))
        except (ValueError, TypeError, OverflowError):
            return 0


class Providers:
    def __init__(self, settings, *, client: httpx.Client | None = None):
        self.s = settings
        self.store = None
        self.client = (
            client
            if client is not None
            else httpx.Client(
                timeout=httpx.Timeout(45, connect=5, pool=5),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                follow_redirects=False,
            )
        )

    def close(self) -> None:
        """Release the connection pool owned by this adapter."""
        self.client.close()

    def request(self, method, url, token, **kwargs):
        provider = {"api.devin.ai": "devin", "api.github.com": "github", "slack.com": "slack"}.get(
            urlparse(url).hostname
        )
        breaker = self.store.recall("breaker:" + provider, {}) if self.store and provider else {}
        if breaker.get("state") == "open":
            # Credit holds stop paid writes but keep existing session observations alive.
            applies = breaker.get("reason") != "credits" or method != "GET"
            if applies and (not breaker.get("retry_at") or breaker["retry_at"] > time.time()):
                raise ProviderError(
                    f"{provider} circuit open: {breaker.get('reason')}",
                    category=breaker.get("reason")
                    if not breaker.get("retry_at")
                    else "circuit_open",
                    retry_after=max(60, breaker.get("retry_at", 0) - time.time()),
                )

        def failed(error):
            if self.store and provider:
                from .resilience import backoff

                failures = breaker.get("failures", 0) + 1
                immediate = error.category in {"credits", "authentication", "rate_limit"}
                if not immediate and not error.retryable:
                    return error
                if immediate or failures >= 3:
                    self.store.remember(
                        "breaker:" + provider,
                        {
                            "state": "open",
                            "reason": error.category,
                            "failures": failures,
                            "retry_at": 0
                            if error.category in {"credits", "authentication"}
                            else time.time() + backoff(failures, error.retry_after),
                        },
                    )
                else:
                    self.store.remember(
                        "breaker:" + provider,
                        {"state": "closed", "failures": failures, "reason": error.category},
                    )
            return error

        try:
            response = self.client.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                **kwargs,
            )
        except httpx.RequestError as e:
            failed(ProviderError(f"Read failed: {type(e).__name__}"))
            if method != "GET":
                raise UnknownEffect(
                    f"{type(e).__name__}; inspect provider before retrying"
                ) from None
            raise ProviderError(f"Read failed: {type(e).__name__}") from None
        if response.status_code >= 500 and method != "GET":
            failed(ProviderError("Provider unavailable", response.status_code))
            raise UnknownEffect(f"Provider {response.status_code}; effect unknown")
        if not response.is_success:
            raise failed(
                ProviderError(
                    f"Provider HTTP {response.status_code}",
                    response.status_code,
                    retry_after=retry_delay(response.headers.get("retry-after")),
                )
            )
        if self.store and provider and breaker.get("reason") != "credits":
            self.store.remember("breaker:" + provider, {"state": "closed", "failures": 0})
        try:
            return response.json() if response.content else None
        except ValueError:
            if method != "GET":
                raise UnknownEffect("Provider returned an unreadable mutation response") from None
            raise ProviderError("Provider returned unreadable JSON") from None

    def gh(self, method, path, **kwargs):
        return self.request(method, "https://api.github.com/" + path, self.s.github_token, **kwargs)

    def devin(self, method, path, **kwargs):
        return self.request(
            method,
            f"https://api.devin.ai/v3/organizations/{self.s.org}/" + path,
            self.s.devin_key,
            **kwargs,
        )

    def create_session(self, payload):
        return self.devin("POST", "sessions", json=payload)

    def session(self, sid):
        return self.devin("GET", f"sessions/{sid}")

    def attachments(self, sid):
        return self.devin("GET", f"sessions/{sid}/attachments")

    def attachment_content(self, attachment, limit=20_000_000):
        """Fetch only provider-confirmed attachment identities; never agent-chosen URLs."""
        try:
            identity = str(UUID(attachment["attachment_id"]))
            name = quote(attachment["name"], safe="")
            endpoint = (
                f"https://api.devin.ai/v3/organizations/{self.s.org}/attachments/{identity}/{name}"
            )
            response = self.client.get(
                endpoint, headers={"Authorization": f"Bearer {self.s.devin_key}"}
            )
            if response.status_code != 307:
                raise ProviderError(
                    f"Attachment download HTTP {response.status_code}",
                    response.status_code,
                    retry_after=retry_delay(response.headers.get("retry-after")),
                )
            location = response.headers.get("location", "")
            parsed = urlparse(location)
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.port not in {None, 443}
                or not (parsed.hostname or "").endswith(".amazonaws.com")
                or ".s3" not in (parsed.hostname or "")
            ):
                raise ProviderError(
                    "Unsupported attachment download destination",
                    category="invalid_artifact",
                    retryable=False,
                )
            # Fresh request: no API credential forwarded to object storage.
            download_request = self.client.build_request("GET", location)
            for header in ("authorization", "cookie"):
                download_request.headers.pop(header, None)
            downloaded = self.client.send(
                download_request, stream=True, auth=None, follow_redirects=False
            )
            try:
                if downloaded.status_code != 200:
                    raise ProviderError(
                        f"Attachment content HTTP {downloaded.status_code}", downloaded.status_code
                    )
                chunks, size = [], 0
                for chunk in downloaded.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ProviderError(
                            "Attachment exceeds the configured size limit",
                            category="invalid_artifact",
                            retryable=False,
                        )
                    chunks.append(chunk)
                return b"".join(chunks), downloaded.headers.get("content-type", "")
            finally:
                downloaded.close()
        except (httpx.RequestError, ValueError, KeyError, TypeError):
            raise ProviderError("Attachment could not be read safely") from None

    def pr(self, number):
        return self.gh("GET", f"repos/{self.s.repo}/pulls/{number}")

    def comment(self, number, body, repository=None):
        return self.gh(
            "POST",
            f"repos/{repository or self.s.repo}/issues/{number}/comments",
            json={"body": body},
        )

    def slack(self, text, key, channel=None):
        result = self.request(
            "POST",
            "https://slack.com/api/chat.postMessage",
            self.s.slack_token,
            json={
                "channel": channel or self.s.slack_channel,
                "text": text,
                "client_msg_id": key,
                "unfurl_links": False,
                "unfurl_media": False,
            },
        )
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise UnknownEffect("Slack returned an unreadable delivery outcome")
        if not result["ok"]:
            error = result.get("error", "unknown")
            if error in {"internal_error", "fatal_error", "unknown"}:
                raise UnknownEffect("Slack delivery effect is uncertain: " + error)
            raise ProviderError("Slack rejected delivery: " + error)
        if not result.get("channel") or not result.get("ts"):
            raise UnknownEffect("Slack acknowledged delivery without a usable receipt")
        return result

    def confirm_publication(self, payload, receipt):
        """Read-only confirmation; retrying this method cannot post another report."""
        if payload["provider"] == "github":
            repo = payload.get("repository", self.s.repo)
            comment = self.gh("GET", f"repos/{repo}/issues/comments/{receipt['id']}")
            if (
                comment.get("body") != payload["body"]
                or comment.get("issue_url")
                != f"https://api.github.com/repos/{repo}/issues/{payload['number']}"
            ):
                raise ProviderError("Published GitHub comment does not match the queued report")
            return comment["html_url"]
        channel = payload.get("channel", self.s.slack_channel)
        if receipt["channel"] != channel:
            raise ProviderError("Slack receipt points to a different destination")
        result = self.request(
            "GET",
            "https://slack.com/api/chat.getPermalink",
            self.s.slack_token,
            params={"channel": channel, "message_ts": receipt["ts"]},
        )
        if not result.get("ok") or result.get("channel") != channel:
            raise ProviderError("Slack message permalink is not confirmed")
        return result["permalink"]
