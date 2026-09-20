"""Common validation for externally supplied evidence links."""

from urllib.parse import urlparse


def safe_link(url):
    if not isinstance(url, str):
        return False
    try:
        p = urlparse(url)
        return (
            p.scheme == "https"
            and bool(p.hostname)
            and not p.username
            and not p.password
            and not any(character.isspace() or ord(character) < 32 for character in url)
            and not any(character in url for character in [")", "<", ">", "\\"])
        )
    except ValueError:
        return False
