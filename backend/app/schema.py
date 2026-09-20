"""Portable relational schema. Epoch timestamps retain double precision on Postgres."""

from sqlalchemy import Column, Float, Integer, MetaData, Table, Text

automation = MetaData()
analytics = MetaData()


def col(name, kind=Text, **options):
    return Column(name, kind, **options)


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
