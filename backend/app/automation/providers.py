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
        return response.json() if response.content else None

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

    def comment(self, number, body):
        return self.gh(
            "POST", f"repos/{self.s.repo}/issues/{number}/comments", json={"body": body}
        )

    def slack(self, text, key):
        result = self.request(
            "POST",
            "https://slack.com/api/chat.postMessage",
            self.s.slack_token,
            json={
                "channel": self.s.slack_channel,
                "text": text,
                "client_msg_id": key,
                "unfurl_links": False,
                "unfurl_media": False,
            },
        )
        if not result.get("ok"):
            raise ProviderError(
                "Slack rejected delivery: " + result.get("error", "unknown")
            )
        return result
