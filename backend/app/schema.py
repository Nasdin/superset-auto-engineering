"""Portable relational schema. Epoch timestamps retain double precision on Postgres."""

from sqlalchemy import Column, Float, Integer, MetaData, Table, Text

automation = MetaData()
analytics = MetaData()


def col(name, kind=Text, **options):
    return Column(name, kind, **options)


# Sidecar table: additive migration, preserving existing jobs and provider receipts.
Table(
    "recovery",
    automation,
    col("key", primary_key=True),
    col("attempts", Integer, nullable=False, server_default="0"),
    col("stage", nullable=False),
    col("category", nullable=False),
    col("next_retry", Float, nullable=False, server_default="0"),
    col("replay_state", nullable=False),
    col("updated", Float, nullable=False),
)


Table(
    "schedules",
    automation,
    col("id", primary_key=True),
    col("name", nullable=False),
    col("enabled", Integer, nullable=False),
    col("interval_seconds", Integer, nullable=False),
    col("next_run", Float, nullable=False),
    col("last_job_id"),
    col("updated", Float, nullable=False),
)


Table(
    "lessons",
    automation,
    col("id", primary_key=True),
    col("job_id", nullable=False),
    col("body", nullable=False),
    col("created", Float, nullable=False),
    col("native_state", nullable=False, server_default="pending"),
    col("note_id"),
)
Table(
    "learning_guard",
    automation,
    col("id", primary_key=True),
    col("owner", nullable=False),
    col("expires", Float, nullable=False),
)
Table(
    "feedback_heads",
    automation,
    col("id", primary_key=True),
    col("source_job_id", nullable=False),
    col("lesson_id", nullable=False),
)
Table(
    "learning_context_history",
    automation,
    col("id", primary_key=True),
    col("job_id", nullable=False),
    col("body", nullable=False),
    col("created", Float, nullable=False),
)
Table(
    "learning_contexts",
    automation,
    col("job_id", primary_key=True),
    col("body", nullable=False),
    col("created", Float, nullable=False),
)
Table(
    "jobs",
    automation,
    col("id", primary_key=True),
    col("dedup", unique=True, nullable=False),
    col("kind", nullable=False),
    col("state", nullable=False),
    col("payload", nullable=False),
    *[col(name) for name in ("session_id", "session_url", "parent_id", "candidate_sha")],
    col("pr_number", Integer),
    col("result"),
    col("error"),
    col("created", Float, nullable=False),
    col("updated", Float, nullable=False),
    *[
        col(name, Float, nullable=False, server_default="0")
        for name in ("next_poll", "lease_until", "acu")
    ],
    col("started", Float),
)
Table("deliveries", automation, col("id", primary_key=True), col("received", Float, nullable=False))
Table(
    "audit",
    automation,
    col("id", Integer, primary_key=True, autoincrement=True),
    col("job_id"),
    col("kind"),
    col("detail"),
    col("created", Float),
)
Table(
    "memory",
    automation,
    col("key", primary_key=True),
    col("value", nullable=False),
    col("updated", Float, nullable=False),
)
Table(
    "publications",
    automation,
    col("key", primary_key=True),
    col("state", nullable=False),
    col("url"),
    col("error"),
    col("updated", Float, nullable=False),
    col("payload"),
    col("receipt"),
)
Table(
    "decisions",
    automation,
    col("id", primary_key=True),
    col("job_id", nullable=False),
    col("sha", nullable=False),
    col("decision", nullable=False),
    col("note", nullable=False),
    col("created", Float, nullable=False),
)
Table(
    "pull_requests",
    analytics,
    col("repository", primary_key=True),
    col("number", Integer, primary_key=True),
    col("data", nullable=False),
)
Table("sync_status", analytics, col("repository", primary_key=True), col("data", nullable=False))

Table(
    "analytics_selections",
    analytics,
    col("selection_id", primary_key=True),
    *[
        col(name, nullable=False)
        for name in (
            "repository",
            "window_end",
            "baseline_end",
            "author",
            "label",
            "base",
            "kind",
            "provenance",
        )
    ],
    col("days", Integer, nullable=False),
    col("requested_at", Float, nullable=False),
)


Table(
    "github_inbox",
    automation,
    col("id", primary_key=True),
    col("payload", nullable=False),
    col("state", nullable=False),
    col("result"),
    col("error"),
    col("lease_token"),
    col("lease_until", Float, nullable=False, server_default="0"),
    col("next_retry", Float, nullable=False, server_default="0"),
    col("created", Float, nullable=False),
    col("updated", Float, nullable=False),
)

Table(
    "analytics_revisions",
    analytics,
    col("repository", primary_key=True),
    col("revision", Integer, nullable=False, server_default="0"),
)
Table(
    "analytics_months",
    analytics,
    col("repository", primary_key=True),
    col("month", primary_key=True),
    col("requested_through", nullable=False),
    col("covered_through"),
    col("state", nullable=False),
    col("progress", nullable=False),
    col("attempts", Integer, nullable=False, server_default="0"),
    col("next_retry", Float, nullable=False, server_default="0"),
    col("lease_token"),
    col("lease_until", Float, nullable=False, server_default="0"),
    col("updated", Float, nullable=False),
)
