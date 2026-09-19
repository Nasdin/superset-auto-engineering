from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database: str = os.getenv("AUTOMATION_DATABASE", "data/automation.db")
    repo: str = os.getenv("GITHUB_REPOSITORY", "Nasdin/superset")
    branch: str = os.getenv("TARGET_BRANCH", "cognition-release-6.1")
    org: str = os.getenv("DEVIN_ORG_ID", "org-f456da0f2e0940808b5c8b3a20312d8c")
    devin_key: str = os.getenv("DEVIN_API_KEY", "")
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    webhook_secret: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    operator_token: str = os.getenv("OPERATOR_TOKEN", "")
    slack_token: str = os.getenv("SLACK_BOT_TOKEN", "")
    slack_channel: str = os.getenv("SLACK_CHANNEL_ID", "")
    label: str = os.getenv("TRIGGER_LABEL", "cognition:repair")
    allowed_actor: str = os.getenv("GITHUB_ALLOWED_ACTOR", "Nasdin")
    max_acu: int = int(os.getenv("DEVIN_MAX_ACU", "10"))
    max_sessions: int = int(os.getenv("DEVIN_MAX_SESSIONS", "6"))
    session_timeout: int = int(os.getenv("SESSION_TIMEOUT_SECONDS", "7200"))
    poll_seconds: int = int(os.getenv("POLL_SECONDS", "30"))
    scan_interval: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "86400"))
    batch_seconds: int = int(os.getenv("BATCH_WINDOW_SECONDS", "60"))
    enabled: bool = os.getenv("AUTOMATION_ENABLED", "false").lower() == "true"
    artifacts: Path = Path(os.getenv("ARTIFACT_DIR", "data/artifacts"))

    def check_repo(self):
        if self.repo.lower() == "apache/superset" or "/" not in self.repo:
            raise ValueError("Automation must target an explicitly configured fork")
