"""Impact reporting contracts against a dedicated disposable Postgres database."""

import json
from datetime import date
from pathlib import Path

from app.analytics.embedding import remember_selection
from test_postgres import postgres  # noqa: F401

REPORTING_SQL = Path(__file__).parents[1] / "app/analytics/reporting.sql"


def install(store):
    with store.connect() as connection:
        for statement in REPORTING_SQL.read_text().split(";"):
            if statement.strip():
                connection.execute(statement)


def select(history, **overrides):
    return remember_selection(
        history,
        {
            "repository": "apache/superset",
            "window_end": "2026-09-20",
            "baseline_end": "2026-03-20",
            "days": 30,
            "author": "",
            "label": "",
            "base": "",
            "kind": "",
            "provenance": "all",
            **overrides,
        },
    )


def seed(history):
    rows = [
        (1, "fix: bot", "automation[bot]", "User", "2026-09-20T23:59:59Z", {}),
        (2, "feat: bot", "robot", "Bot", "2026-09-15T00:00:00Z", {}),
        (
            3,
            "fix: known",
            "engineer",
            "User",
            "2026-09-20T01:00:00Z",
            {
                "commits_count": 4,
                "rework_commits": 0,
                "additions": 10,
                "deletions": 5,
            },
        ),
        (4, "fix: unknown", "engineer", "User", "2026-09-20T02:00:00Z", {}),
        (
            5,
            "feat: known",
            "engineer",
            "User",
            "2026-09-20T03:00:00Z",
            {
                "commits_count": 1,
                "rework_commits": 2,
                "additions": 20,
                "deletions": 0,
            },
        ),
        (6, "docs: first month", "engineer", "User", "2026-03-01T00:00:00Z", {}),
        (7, "docs: before month range", "engineer", "User", "2026-02-28T23:59:59Z", {}),
        (8, "fix: future must be excluded", "engineer", "User", "2026-09-21T00:00:00Z", {}),
        (9, "docs: rolling start", "engineer", "User", "2026-08-22T00:00:00Z", {}),
        (10, "docs: before rolling start", "engineer", "User", "2026-08-21T23:59:59Z", {}),
    ]
    with history.connect() as connection:
        for number, title, author, author_type, merged, details in rows:
            doc = {
                "number": number,
                "title": title,
                "author": author,
                "author_type": author_type,
                "url": f"https://github.com/apache/superset/pull/{number}",
                "labels": [],
                "base": "master",
                "state": "closed",
                "created_at": "2026-02-01T00:00:00Z",
                "merged_at": merged,
                "closed_at": merged,
                **details,
            }
            connection.execute(
                "INSERT INTO pull_requests(repository,number,data) VALUES(:repo,:number,:data)",
                {"repo": "apache/superset", "number": number, "data": json.dumps(doc)},
            )
    history.set_status(
        "apache/superset",
        {
            "complete": True,
            "coverage_from": "2020-01-01",
            "last_success": "2026-09-21T00:00:00Z",
        },
    )


def rows(history, view, identity, suffix=""):
    with history.connect() as connection:
        return connection.execute(
            f"SELECT * FROM reporting.{view} WHERE selection_id=:id {suffix}", {"id": identity}
        ).fetchall()


def test_impact_periods_segments_and_missing_measurements(postgres):  # noqa: F811
    store, history = postgres
    seed(history)
    install(store)
    install(store)  # Reprovisioning preserves dependencies and existing view columns.
    identity = select(history)
    monthly = rows(history, "impact_monthly", identity)
    assert len(monthly) == 7 * 4
    assert min(row["month"] for row in monthly) == date(2026, 3, 1)
    assert max(row["window_end"] for row in monthly) == date(2026, 9, 20)
    assert sum(row["merged_prs"] for row in monthly) == 8
    september = {row["segment"]: row for row in monthly if row["month"] == date(2026, 9, 1)}
    assert september["Bots"]["merged_prs"] == 2
    fixes = september["Fixes"]
    assert fixes["merged_prs"] == 2
    assert fixes["commits_samples"] == fixes["code_samples"] == fixes["rework_samples"] == 1
    assert fixes["avg_commits"] == 4
    assert fixes["avg_rework"] == 0  # Measured zero survives; absent review data stays null.
    assert fixes["avg_lines_changed"] == 15
    assert fixes["additions"] == 10 and fixes["deletions"] == 5
    assert september["Bots"]["avg_commits"] is None
    assert september["Bots"]["additions"] is None
    assert september["Other"]["merged_prs"] == 0
    assert september["Other"]["median_hours"] is None
    assert all(row["history_covered"] for row in monthly)
    rolling = rows(history, "impact_rolling", identity)
    assert len(rolling) == 27 * 4
    current = [row for row in rolling if row["window_end"] == date(2026, 9, 20)]
    assert {row["window_start"] for row in current} == {date(2026, 8, 22)}
    assert sum(row["merged_prs"] for row in current) == 6
    assert (
        sum(
            row["merged_prs"]
            for row in rows(history, "impact_categories", identity)
            if row["cohort"] == "Current"
        )
        == 6
    )
    assert len(rows(history, "details", identity)) == 6


def test_impact_filters_selection_isolation_and_axis_extent(postgres):  # noqa: F811
    store, history = postgres
    seed(history)
    install(store)
    bots = select(history, kind="bot")
    fixes = select(history, kind="fix")
    assert sum(row["merged_prs"] for row in rows(history, "impact_monthly", bots)) == 2
    assert sum(row["merged_prs"] for row in rows(history, "impact_monthly", fixes)) == 3
    assert {row["segment"] for row in rows(history, "details", bots)} == {"Bots"}
    exact = select(history, kind="fix", author="engineer", base="master")
    assert len(rows(history, "details", exact)) == 2
    no_match = select(history, author="engineer' OR true --")
    assert all(row["merged_prs"] == 0 for row in rows(history, "impact_monthly", no_match))
    extent = rows(history, "impact_monthly_chart", bots, "AND chart_date=DATE '2026-09-24'")
    assert len(extent) == 4
    assert all(
        row[metric] is None
        for row in extent
        for metric in (
            "median_hours",
            "avg_commits",
            "avg_rework",
            "avg_lines_changed",
        )
    )
    assert all(row["month"] <= date(2026, 9, 20) for row in rows(history, "impact_monthly", bots))


def test_impact_history_coverage_is_per_period(postgres):  # noqa: F811
    store, history = postgres
    seed(history)
    install(store)
    history.set_status(
        "apache/superset",
        {
            "complete": True,
            "coverage_from": "2026-03-02",
            "last_success": "2026-09-20T23:59:59Z",
        },
    )
    identity = select(history)
    monthly = rows(history, "impact_monthly", identity)
    for row in monthly:
        assert row["history_covered"] == (4 <= row["month"].month <= 8)
    absent = select(history, repository="Nasdin/superset")
    assert all(not row["history_covered"] for row in rows(history, "impact_rolling", absent))


def test_impact_charts_hide_uncovered_periods_and_do_not_extend_historic_ranges(postgres):  # noqa: F811
    store, history = postgres
    seed(history)
    install(store)
    identity = select(history)
    measured = rows(
        history,
        "impact_monthly_chart",
        identity,
        "AND chart_date=DATE '2026-09-01' AND segment='Fixes'",
    )
    assert measured[0]["avg_commits"] == 4
    history.set_status(
        "apache/superset",
        {
            "complete": True,
            "coverage_from": "2020-01-01",
            "last_success": "2026-09-20T23:59:59Z",
        },
    )
    unmeasured = rows(
        history,
        "impact_monthly_chart",
        identity,
        "AND chart_date=DATE '2026-09-01' AND segment='Fixes'",
    )
    assert all(
        unmeasured[0][metric] is None
        for metric in (
            "median_hours",
            "avg_commits",
            "avg_rework",
            "avg_lines_changed",
        )
    )
    historic = select(history, window_end="2025-09-20", baseline_end="2025-03-20")
    for view in ("impact_monthly_chart", "impact_rolling_chart"):
        assert max(row["chart_date"] for row in rows(history, view, historic)) == date(2025, 9, 20)
