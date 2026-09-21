import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database: str = field(default="data/automation.db", repr=False)
    repo: str = "Nasdin/superset"
    branch: str = "cognition-release-6.1"
    org: str = "org-f456da0f2e0940808b5c8b3a20312d8c"
    devin_key: str = field(default="", repr=False)
    github_token: str = field(default="", repr=False)
    webhook_secret: str = field(default="", repr=False)
    operator_token: str = field(default="", repr=False)
    slack_token: str = field(default="", repr=False)
    slack_channel: str = ""
    label: str = "cognition:repair"
    allowed_actor: str = "Nasdin"
    max_acu: int = 10
    max_sessions: int = 6
    session_timeout: int = 7200
    poll_seconds: int = 30
    scan_interval: int = 86400
    batch_seconds: int = 60
    dependabot_enabled: bool = True
    learning_enabled: bool = True
    enabled: bool = False
    autonomous_remediation: bool = True
    max_remediation_attempts: int = 2
    max_handoff_followups: int = 1
    cloudflare_account_id: str = ""
    cloudflare_audit_secret_id: str = field(default="", repr=False)
    evidence_public_url: str = ""
    artifacts: Path = Path("data/artifacts")

    @property
    def analytics_database(self):
        return (
            self.database
            if self.database.startswith("postgresql")
            else str(Path(self.database).with_name("analytics.db"))
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        """Read configuration at startup, not at module import time."""
        env = os.environ if environ is None else environ
        values = {}
        for name in ("cloudflare_account_id", "cloudflare_audit_secret_id"):
            if name.upper() in env:
                values[name] = str(env[name.upper()])
        if "AUTOMATION_DATABASE" in env:
            values["database"] = str(env["AUTOMATION_DATABASE"])
        if "GITHUB_REPOSITORY" in env:
            values["repo"] = str(env["GITHUB_REPOSITORY"])
        if "TARGET_BRANCH" in env:
            values["branch"] = str(env["TARGET_BRANCH"])
        if "DEVIN_ORG_ID" in env:
            values["org"] = str(env["DEVIN_ORG_ID"])
        if "DEVIN_API_KEY" in env:
            values["devin_key"] = str(env["DEVIN_API_KEY"])
        if "GITHUB_TOKEN" in env:
            values["github_token"] = str(env["GITHUB_TOKEN"])
        if "GITHUB_WEBHOOK_SECRET" in env:
            values["webhook_secret"] = str(env["GITHUB_WEBHOOK_SECRET"])
        if "OPERATOR_TOKEN" in env:
            values["operator_token"] = str(env["OPERATOR_TOKEN"])
        if "SLACK_BOT_TOKEN" in env:
            values["slack_token"] = str(env["SLACK_BOT_TOKEN"])
        if "SLACK_CHANNEL_ID" in env:
            values["slack_channel"] = str(env["SLACK_CHANNEL_ID"])
        if "TRIGGER_LABEL" in env:
            values["label"] = str(env["TRIGGER_LABEL"])
        if "GITHUB_ALLOWED_ACTOR" in env:
            values["allowed_actor"] = str(env["GITHUB_ALLOWED_ACTOR"])
        if "DEVIN_MAX_ACU" in env:
            values["max_acu"] = int(env["DEVIN_MAX_ACU"])
        if "DEVIN_MAX_SESSIONS" in env:
            values["max_sessions"] = int(env["DEVIN_MAX_SESSIONS"])
        if "SESSION_TIMEOUT_SECONDS" in env:
            values["session_timeout"] = int(env["SESSION_TIMEOUT_SECONDS"])
        if "POLL_SECONDS" in env:
            values["poll_seconds"] = int(env["POLL_SECONDS"])
        if "SCAN_INTERVAL_SECONDS" in env:
            values["scan_interval"] = int(env["SCAN_INTERVAL_SECONDS"])
        if "BATCH_WINDOW_SECONDS" in env:
            values["batch_seconds"] = int(env["BATCH_WINDOW_SECONDS"])
        if "LEARNING_ENABLED" in env:
            values["learning_enabled"] = env["LEARNING_ENABLED"].lower() == "true"
        if "DEPENDABOT_ENABLED" in env:
            values["dependabot_enabled"] = env["DEPENDABOT_ENABLED"].lower() == "true"
        if "AUTONOMOUS_REMEDIATION" in env:
            values["autonomous_remediation"] = env["AUTONOMOUS_REMEDIATION"].lower() == "true"
        if "MAX_REMEDIATION_ATTEMPTS" in env:
            values["max_remediation_attempts"] = int(env["MAX_REMEDIATION_ATTEMPTS"])
        if "AUTOMATION_ENABLED" in env:
            values["enabled"] = env["AUTOMATION_ENABLED"].lower() == "true"
        if "EVIDENCE_PUBLIC_URL" in env:
            values["evidence_public_url"] = env["EVIDENCE_PUBLIC_URL"].rstrip("/")
        if "ARTIFACT_DIR" in env:
            values["artifacts"] = Path(env["ARTIFACT_DIR"])
        if env.get("DATABASE_URL"):
            values["database"] = env["DATABASE_URL"]
        settings = cls(**values)
        settings.check_repo()
        return settings

    def check_repo(self):
        if self.repo.lower() == "apache/superset" or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo
        ):
            raise ValueError("Automation must target an explicitly configured fork")

        if not self.branch or not self.org:
            raise ValueError("Branch and Devin organization are required")
        if (
            self.max_acu <= 0
            or self.max_sessions < 0
            or self.poll_seconds <= 0
            or self.session_timeout <= 0
            or self.scan_interval < 0
            or self.batch_seconds < 0
            or not 0 <= self.max_remediation_attempts <= 3
            or not 0 <= self.max_handoff_followups <= 2
        ):
            raise ValueError(
                "Execution limits must be positive; session/scan/batch limits may be zero"
            )
