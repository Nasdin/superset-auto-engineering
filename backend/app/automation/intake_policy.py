"""Opt-in automatic intake can start at a rollout boundary without replaying backlog."""

from datetime import datetime


def automatic_intake(settings, document):
    if not settings.automatic_intake:
        return False
    if not settings.automatic_intake_since:
        return True
    try:
        created = datetime.fromisoformat(document.get("created_at", "").replace("Z", "+00:00"))
        since = datetime.fromisoformat(settings.automatic_intake_since.replace("Z", "+00:00"))
        return created >= since
    except (ValueError, TypeError):
        return False
