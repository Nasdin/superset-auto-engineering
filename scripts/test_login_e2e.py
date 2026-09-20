"""Run the login browser test with a disposable password and isolated databases."""

import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.passwords import hash_password  # noqa: E402

if __name__ == "__main__":
    password = secrets.token_urlsafe(24)
    environment = {
        **os.environ,
        "TEST_PYTHON": sys.executable,
        "AUTH_ENABLED": "true",
        "AUTH_COOKIE_SECURE": "false",
        "REVIEWER_PASSWORD_HASH": hash_password(password),
        "AUTH_E2E_PASSWORD": password,
    }
    # Always start the temporary fixture server, never authenticate to a live host.
    environment.pop("E2E_BASE_URL", None)
    environment.pop("AUTH_GATEWAY_URL", None)
    raise SystemExit(
        subprocess.run(
            ["npx", "playwright", "test", "tests/auth.spec.ts"],
            cwd=ROOT / "frontend",
            env=environment,
            check=False,
        ).returncode
    )
