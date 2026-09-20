"""Generate local setup secrets without printing or replacing nonempty values."""

import argparse
import secrets
from pathlib import Path

SECRET_KEYS = (
    "POSTGRES_ADMIN_PASSWORD",
    "POSTGRES_APP_PASSWORD",
    "POSTGRES_SUPERSET_PASSWORD",
    "POSTGRES_READER_PASSWORD",
    "ANALYTICS_SUPERSET_SECRET_KEY",
    "ANALYTICS_SUPERSET_ADMIN_PASSWORD",
    "ANALYTICS_SUPERSET_SERVICE_PASSWORD",
    "OPERATOR_TOKEN",
    "GITHUB_WEBHOOK_SECRET",
)
DEFAULTS = {
    "SUPERSET_INTERNAL_URL": "http://analytics-superset:8088/bi",
    "SUPERSET_PUBLIC_URL": "http://127.0.0.1:8189/bi",
    "SUPERSET_ALLOWED_ORIGINS": "http://127.0.0.1:8000,http://localhost:8000",
}


def configure(path: Path) -> int:
    lines = path.read_text().splitlines() if path.exists() else []
    known = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            known[key.strip()] = value.strip()
    values = {
        key: secrets.token_hex(32)
        for key in SECRET_KEYS
        if not known.get(key, "").strip("\"'")
    }
    values.update({key: value for key, value in DEFAULTS.items() if key not in known})
    # Replace explicitly blank secrets instead of accumulating duplicate keys.
    output = [line for line in lines if line.partition("=")[0].strip() not in values]
    output.extend(f"{key}={value}" for key, value in values.items())
    if values or not path.exists():
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        path.write_text("\n".join(output) + "\n")
    else:
        path.chmod(0o600)
    return len(values)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env"
    )
    count = configure(parser.parse_args().env_file)
    print(
        f"Configured {count} missing/empty local settings; secret values were not printed."
    )
