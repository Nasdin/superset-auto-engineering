"""Create missing local database/BI credentials without printing or replacing secrets."""

from pathlib import Path
import secrets

path = Path(__file__).resolve().parents[1] / ".env"
content = path.read_text() if path.exists() else ""
known = {line.partition("=")[0] for line in content.splitlines() if "=" in line}
values = {}
for key in (
    "POSTGRES_ADMIN_PASSWORD",
    "POSTGRES_APP_PASSWORD",
    "POSTGRES_SUPERSET_PASSWORD",
    "POSTGRES_READER_PASSWORD",
    "ANALYTICS_SUPERSET_SECRET_KEY",
    "ANALYTICS_SUPERSET_ADMIN_PASSWORD",
    "ANALYTICS_SUPERSET_SERVICE_PASSWORD",
):
    if key not in known:
        values[key] = secrets.token_hex(32)
for key, value in {
    "SUPERSET_INTERNAL_URL": "http://analytics-superset:8088/bi",
    "SUPERSET_PUBLIC_URL": "http://127.0.0.1:8189/bi",
    "SUPERSET_ALLOWED_ORIGINS": "http://127.0.0.1:8000,http://localhost:8000",
}.items():
    if key not in known:
        values[key] = value
with path.open("a") as output:
    output.write("\n" + "\n".join(f"{k}={v}" for k, v in values.items()) + "\n")
path.chmod(0o600)
print(
    f"Configured {len(values)} missing local settings; secret values were not printed."
)
