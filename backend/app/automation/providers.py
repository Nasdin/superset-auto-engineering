"""Provider adapters; no retry of uncertain mutations, no credential logging."""

import httpx


class UnknownEffect(Exception):
    pass


class ProviderError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Providers:
    def __init__(self, settings):
        self.s = settings
        self.client = httpx.Client(timeout=45, follow_redirects=False)

    def request(self, method, url, token, **kwargs):
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
            if method != "GET":
                raise UnknownEffect(
                    f"{type(e).__name__}; inspect provider before retrying"
                ) from None
            raise ProviderError(f"Read failed: {type(e).__name__}") from None
        if response.status_code >= 500 and method != "GET":
            raise UnknownEffect(f"Provider {response.status_code}; effect unknown")
        if not response.is_success:
            raise ProviderError(
                f"Provider HTTP {response.status_code}", response.status_code
            )
        try:
            return response.json() if response.content else None
        except ValueError:
            if method != "GET":
                raise UnknownEffect(
                    "Provider returned an unreadable mutation response"
                ) from None
            raise ProviderError("Provider returned unreadable JSON") from None

    def gh(self, method, path, **kwargs):
        return self.request(
            method, "https://api.github.com/" + path, self.s.github_token, **kwargs
        )

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
                raise ProviderError(
                    "Published GitHub comment does not match the queued report"
                )
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
