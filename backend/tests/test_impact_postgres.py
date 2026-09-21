"""Impact reporting contracts against a dedicated disposable Postgres database."""

import json
from datetime import date
from pathlib import Path

from app.analytics.classification import SEGMENTS
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
    assert len(monthly) == 7 * len(SEGMENTS)
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
    assert september["Documentation"]["merged_prs"] == 0
    assert september["Documentation"]["median_hours"] is None
    assert all(row["history_covered"] for row in monthly)
    rolling = rows(history, "impact_rolling", identity)
    assert len(rolling) == 27 * len(SEGMENTS)
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
    assert len(extent) == len(SEGMENTS)
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


def test_monthly_total_sums_selected_pr_durations_and_preserves_missingness(postgres):  # noqa: F811
    from app.analytics.impact import impact_report
    from test_analytics import record

    store, history = postgres
    install(store)
    selected = [
        record(1, created="2026-02-28T23:00:00Z", merged="2026-03-01T01:00:00Z"),
        record(
            2,
            created="2026-03-31T20:00:00Z",
            merged="2026-03-31T23:00:00Z",
            author="dependabot[bot]",
        ),
        record(3, created="2026-03-31T23:00:00Z", merged="2026-04-01T01:00:00Z"),
        record(4, created="2026-03-01T00:00:00Z", merged=None),
        record(5, created="2026-09-21T00:00:00Z", merged="2026-09-21T01:00:00Z"),
    ]
    with history.connect() as connection:
        for pr in selected:
            connection.execute(
                "INSERT INTO pull_requests(repository,number,data) VALUES(:repo,:number,:data)",
                {"repo": "apache/superset", "number": pr["number"], "data": json.dumps(pr)},
            )
    status = {
        "complete": True,
        "coverage_from": "2020-01-01",
        "last_success": "2026-09-21T00:00:00Z",
    }
    history.set_status("apache/superset", status)
    identity = select(history)
    chart = rows(history, "impact_total_monthly_chart", identity)
    by_month = {row["chart_date"].isoformat(): row["total_hours"] for row in chart}
    python = impact_report(
        selected,
        status,
        end=date(2026, 9, 20),
        days=30,
        baseline_end=date(2026, 3, 20),
        tracked=set(),
    )
    assert all(
        by_month[row["month"]] == row["covered_total_hours"] for row in python["monthly_totals"]
    )
    assert by_month["2026-03-01"] == 5
    assert by_month["2026-04-01"] == 2
    assert by_month["2026-05-01"] == 0
    assert by_month["2026-09-24"] is None  # Annotation extent cannot invent data.
    bot_selection = select(history, kind="bot")
    bot_march = rows(
        history, "impact_total_monthly_chart", bot_selection, "AND chart_date=DATE '2026-03-01'"
    )
    assert bot_march[0]["total_hours"] == 3
    fork = select(history, repository="Nasdin/superset")
    assert all(
        row["total_hours"] is None for row in rows(history, "impact_total_monthly_chart", fork)
    )
    invalid = record(6, created="2026-03-02T00:00:00Z", merged="2026-03-01T00:00:00Z")
    with history.connect() as connection:
        connection.execute(
            "INSERT INTO pull_requests(repository,number,data) VALUES(:repo,:number,:data)",
            {"repo": "apache/superset", "number": 6, "data": json.dumps(invalid)},
        )
    assert (
        rows(history, "impact_total_monthly_chart", identity, "AND chart_date=DATE '2026-03-01'")[
            0
        ]["total_hours"]
        is None
    )
    history.set_status("apache/superset", {**status, "complete": False})
    assert all(
        row["total_hours"] is None for row in rows(history, "impact_total_monthly_chart", identity)
    )


def test_lazy_month_coverage_drives_native_charts_and_reader_can_query(postgres):  # noqa: F811
    store, history = postgres
    seed(history)
    history.set_status("apache/superset", {"complete": False})
    install(store)
    identity = select(history)
    with history.connect() as connection:
        for month, requested, covered, state in (
            ("2026-03-01", "2026-03-31", "2026-03-31", "complete"),
            ("2026-08-01", "2026-08-31", "2026-08-31", "complete"),
            ("2026-09-01", "2026-09-30", "2026-09-20", "running"),
        ):
            connection.execute(
                "INSERT INTO analytics_months(repository,month,requested_through,covered_through,"
                "state,progress,updated) VALUES(:repo,:month,:requested,:covered,:state,'{}',0)",
                {
                    "repo": "apache/superset",
                    "month": month,
                    "requested": requested,
                    "covered": covered,
                    "state": state,
                },
            )
        # Verify the actual Superset read-only role, not merely the test DB owner.
        connection.execute("SET LOCAL ROLE cognition_reader")
        chart = connection.execute(
            "SELECT chart_date,total_hours FROM reporting.impact_total_monthly_chart "
            "WHERE selection_id=:id",
            {"id": identity},
        ).fetchall()
    values = {row["chart_date"]: row["total_hours"] for row in chart}
    assert values[date(2026, 3, 1)] is not None
    assert values[date(2026, 4, 1)] is None
    assert values[date(2026, 9, 1)] is not None  # A verified prefix survives continued import.
    assert all(
        row["history_covered"]
        for row in rows(history, "impact_rolling", identity)
        if row["window_end"] == date(2026, 9, 20)
    )
    tomorrow = select(history, window_end="2026-09-21")
    assert (
        rows(history, "impact_total_monthly_chart", tomorrow, "AND chart_date=DATE '2026-09-01'")[
            0
        ]["total_hours"]
        is None
    )


def test_explicit_month_gap_overrides_broad_coverage_until_verified(postgres):  # noqa: F811
    store, history = postgres
    seed(history)  # Broad horizon says every displayed month is complete.
    install(store)
    identity = select(history)
    with history.connect() as connection:
        connection.execute(
            "INSERT INTO analytics_months(repository,month,requested_through,covered_through,"
            "state,progress,updated) VALUES('apache/superset','2026-09-01','2026-09-30',NULL,"
            "'queued','{}',0)"
        )
    monthly = rows(history, "impact_total_monthly_chart", identity)
    values = {row["chart_date"]: row["total_hours"] for row in monthly}
    assert values[date(2026, 9, 1)] is None
    assert values[date(2026, 3, 1)] is not None  # No explicit gap: broad proof still applies.
    current = [
        row
        for row in rows(history, "impact_rolling", identity)
        if row["window_end"] == date(2026, 9, 20)
    ]
    assert all(not row["history_covered"] for row in current)
    with history.connect() as connection:
        connection.execute(
            "UPDATE analytics_months SET state='retry',covered_through='2026-09-20' "
            "WHERE repository='apache/superset' AND month='2026-09-01'"
        )
    assert (
        rows(history, "impact_total_monthly_chart", identity, "AND chart_date=DATE '2026-09-01'")[
            0
        ]["total_hours"]
        is not None
    )
    tomorrow = select(history, window_end="2026-09-21")
    assert (
        rows(history, "impact_total_monthly_chart", tomorrow, "AND chart_date=DATE '2026-09-01'")[
            0
        ]["total_hours"]
        is None
    )


def test_category_totals_classification_parity_and_conservation(postgres):  # noqa: F811
    from app.analytics.classification import classify
    from app.analytics.impact import impact_report, segment
    from test_analytics import record
    from test_classification import CASES

    store, history = postgres
    docs = [
        record(
            i,
            title=title,
            labels=labels,
            created="2026-09-01T00:00:00Z",
            merged=f"2026-09-01T{(i % 23):02}:00:00Z",
        )
        for i, (title, labels, _) in enumerate(CASES, 1)
    ]
    docs += [record(100, title="feat: bot", author="builder[bot]", labels=[])]
    docs += [record(39640, title="Sl permissions", labels=[])]
    with history.connect() as c:
        for pr in docs:
            c.execute(
                "INSERT INTO pull_requests(repository,number,data) VALUES(:r,:n,:d)",
                {"r": "apache/superset", "n": pr["number"], "d": json.dumps(pr)},
            )
    status = {
        "complete": True,
        "coverage_from": "2020-01-01",
        "last_success": "2026-09-21T00:00:00Z",
    }
    history.set_status("apache/superset", status)
    install(store)
    identity = select(history)
    sql_docs = {row["number"]: row for row in rows(history, "details", identity)}
    for pr in docs:
        row = sql_docs[pr["number"]]
        assert (row["category"], row["classification_reason"]) == classify(pr)
        assert row["segment"] == segment(pr)
    python = impact_report(
        docs, status, end=date(2026, 9, 20), days=30, baseline_end=date(2026, 3, 20), tracked=set()
    )
    chart = rows(history, "impact_segment_total_monthly_chart", identity)
    actual = {
        (row["chart_date"].isoformat(), row["segment"]): row["segment_total_hours"] for row in chart
    }
    for row in python["monthly"]:
        assert actual[row["month"], row["segment"]] == row["covered_total_hours"]
    for row in rows(history, "impact_total_monthly_chart", identity):
        if row["total_hours"] is not None:
            assert (
                sum(r["segment_total_hours"] for r in chart if r["chart_date"] == row["chart_date"])
                == row["total_hours"]
            )
    assert all(
        r["segment_total_hours"] is None for r in chart if r["chart_date"] == date(2026, 9, 24)
    )
    assert (
        sum(
            r["segment_total_hours"] or 0
            for r in rows(
                history, "impact_segment_total_monthly_chart", select(history, kind="bot")
            )
        )
        == 216
    )
    assert all(
        r["segment_total_hours"] is None
        for r in rows(
            history,
            "impact_segment_total_monthly_chart",
            select(history, repository="Nasdin/superset"),
        )
    )
    # An invalid duration must not turn into a deceptively complete category total.
    invalid = record(999, created="2026-09-11T00:00:00Z", merged="2026-09-10T00:00:00Z")
    with history.connect() as c:
        c.execute(
            "INSERT INTO pull_requests(repository,number,data) VALUES(:r,:n,:d)",
            {"r": "apache/superset", "n": 999, "d": json.dumps(invalid)},
        )
    invalid_chart = rows(
        history, "impact_segment_total_monthly_chart", identity, "AND chart_date=DATE '2026-09-01'"
    )
    by_type = {r["segment"]: r["segment_total_hours"] for r in invalid_chart}
    assert by_type["Fixes"] is None
    assert by_type["Bots"] == 216
    history.set_status("apache/superset", {})
    assert all(
        r["segment_total_hours"] is None
        for r in rows(history, "impact_segment_total_monthly_chart", identity)
    )


def test_focus_periods_match_bounded_python_and_isolate_repository(postgres):  # noqa: F811
    from app.analytics.impact import impact_report

    store, history = postgres
    seed(history)
    install(store)
    identity = select(history, days=31)
    reference = impact_report(
        history.pulls("apache/superset"),
        history.status("apache/superset"),
        end=date(2026, 9, 20),
        days=31,
        baseline_end=date(2026, 3, 20),
        tracked=set(),
        bounded=True,
    )
    for cadence in ("monthly", "weekly"):
        actual = rows(history, f"focus_{cadence}_chart", identity)
        assert {r["segment"] for r in actual} == {"Fixes", "Features", "Bots"}
        for expected in reference[cadence]:
            if expected["segment"] not in {"Fixes", "Features", "Bots"}:
                continue
            found = next(
                r
                for r in actual
                if r["chart_date"].isoformat() == expected["month"]
                and r["segment"] == expected["segment"]
            )
            for metric in ("avg_commits", "median_hours", "avg_rework", "avg_lines_changed"):
                assert found[metric] == expected[metric]
            assert found["segment_total_hours"] == expected["covered_total_hours"]
    absent = select(history, repository="Nasdin/superset", days=31)
    assert all(r["median_hours"] is None for r in rows(history, "focus_weekly_chart", absent))
