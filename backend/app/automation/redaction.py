"""Defense in depth for public agent text; raw artifacts must be sanitized at capture."""

import re

SECRET_FIELDS = r"authorization|proxy-authorization|cookie|set-cookie|x-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret|x-csrftoken|x-csrf-token|csrf[_-]?token"


def redact_text(value, secrets=()):
    text = str(value)
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\bBearer\s+(?!\$)[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(rf"(?i)([?&](?:{SECRET_FIELDS})=)[^\s&'\"]+", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?im)(\b[A-Z][A-Z0-9_]*(?:PASSWORD|SECRET|SECRET_KEY|TOKEN|API_KEY)\s*=\s*)(?:\"[^\"]*\"|'[^']*'|[^\s]+)",
        r"\1[REDACTED]",
        text,
    )
    # curl credentials can be positional option values, not named headers.
    text = re.sub(
        r"""(?i)((?:--(?:user|proxy-user|cookie|oauth2-bearer)(?:=|\s+)|(?<!\S)-[ubU]\s*))(?:"[^"]*"|'[^']*'|[^\s]+)""",
        r"\1'[REDACTED]'",
        text,
    )
    # Headers and quoted/unquoted key-value pairs, including JSON response snippets.
    text = re.sub(
        rf"""(?i)(["']?(?:{SECRET_FIELDS})["']?\s*[:=]\s*)(["'])(.*?)\2""", r'\1"[REDACTED]"', text
    )
    text = re.sub(
        rf"""(?im)(\b(?:{SECRET_FIELDS})\s*[:=]\s*)(?!["'])([^\r\n"']+)""", r"\1[REDACTED]", text
    )
    return text


def sanitize(value, secrets=()):
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]" if re.fullmatch(SECRET_FIELDS, key, re.I) else sanitize(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item, secrets) for item in value]
    return redact_text(value, secrets) if isinstance(value, str) else value


def provider_secrets(settings):
    return tuple(
        getattr(settings, field)
        for field in (
            "devin_key",
            "github_token",
            "webhook_secret",
            "operator_token",
            "slack_token",
        )
    )
