"""Set the shared reviewer password interactively; never print or commit it."""

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.passwords import hash_password  # noqa: E402


def configure(path: Path, password: str, *, secure: bool):
    if not 12 <= len(password) <= 256:
        raise ValueError("Use a password between 12 and 256 characters")
    updates = {
        "AUTH_ENABLED": "true",
        "AUTH_COOKIE_SECURE": str(secure).lower(),
        "REVIEWER_PASSWORD_HASH": hash_password(password),
    }
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [
        line
        for line in lines
        if line.partition("=")[0].strip() not in {*updates, "REVIEWER_USER"}
    ]
    lines.extend(f"{key}={value}" for key, value in updates.items())
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--local-http",
        action="store_true",
        help="Allow cookies over local development HTTP only",
    )
    args = parser.parse_args()
    password = getpass.getpass("Reviewer password: ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    configure(args.env_file, password, secure=not args.local_http)
    print(
        "Login configured. Recreate the API container. Existing sessions are revoked on restart."
    )
