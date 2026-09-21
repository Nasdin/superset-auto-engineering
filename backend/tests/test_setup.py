"""Setup must be repeatable without rotating existing installation secrets."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUP = runpy.run_path(str(ROOT / "scripts" / "configure_local_postgres.py"))


def test_fresh_env_generates_secrets_and_rerun_is_non_destructive(tmp_path):
    env = tmp_path / ".env"
    env.write_text((ROOT / ".env.example").read_text())
    assert SETUP["configure"](env) > 0
    configured = env.read_text()
    values = dict(
        line.split("=", 1)
        for line in configured.splitlines()
        if "=" in line and not line.startswith("#")
    )
    assert all(len(values[key]) == 64 for key in SETUP["SECRET_KEYS"])
    assert values["AUTOMATION_ENABLED"] == "false"
    assert "http://127.0.0.1:5173" in values["SUPERSET_ALLOWED_ORIGINS"]
    assert env.stat().st_mode & 0o777 == 0o600
    assert SETUP["configure"](env) == 0
    assert env.read_text() == configured


def test_empty_defaults_are_repaired_but_existing_credentials_and_urls_survive(tmp_path):
    env = tmp_path / ".env"
    original = (
        "POSTGRES_APP_PASSWORD=literal$credential\nSUPERSET_PUBLIC_URL=https://bi.example/bi\n"
    )
    env.write_text(original + "SUPERSET_INTERNAL_URL=''\nSUPERSET_ALLOWED_ORIGINS=\n")
    SETUP["configure"](env)
    configured = env.read_text()
    assert original in configured
    assert "SUPERSET_INTERNAL_URL=http://analytics-superset:8088/bi\n" in configured
    assert configured.count("SUPERSET_ALLOWED_ORIGINS=") == 1
    assert "http://127.0.0.1:5173" in configured
