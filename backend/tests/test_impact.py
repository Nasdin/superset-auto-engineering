from datetime import date

from app.analytics.impact import impact_report, is_bot, measure, segment
from app.analytics.metrics import analyze
from test_analytics import record

STATUS = {"complete": True, "coverage_from": "2020-01-01", "last_success": "2026-10-21T00:00:00Z"}


def report(rows, end=date(2026, 9, 20), tracked=None):
    return impact_report(
        rows,
        STATUS,
        end=end,
        days=30,
        baseline_end=date(2026, 3, 20),
        tracked=tracked or set(),
        completed=tracked or set(),
    )


def test_unknown_is_not_zero_and_bot_groups_never_double_count():
    rows = [
        record(1, author="automation[bot]", author_type=None),
        record(2),
        record(3, title="feat: charts", labels=[]),
        record(4, title="docs", labels=[]),
    ]
    result = report(rows)
    assert {
        row["segment"]: row["current"]["merged_prs"]
        for row in result["categories"]
        if row["current"]["merged_prs"]
    } == {"Fixes": 1, "Features": 1, "Bots": 1, "Documentation": 1}
    assert sum(row["current"]["merged_prs"] for row in result["categories"]) == 4
    assert result["current"]["avg_commits"] is None
    assert result["current"]["additions"] is None
    assert result["current"]["code_samples"] == 0
    assert is_bot(record(author_type="Bot"))
    assert segment(record(author_type="Bot")) == "Bots"
    assert not is_bot(record(author_type=None))


def test_rework_counts_measured_zero_and_code_uses_paired_values():
    result = measure(
        [
            record(1, commits_count=2, rework_commits=0, additions=20, deletions=10),
            record(2, commits_count=4, additions=50),
            record(3),
        ]
    )
    assert result["avg_commits"] == 3
    assert result["commits_samples"] == 2
    assert result["avg_rework"] == 0
    assert result["rework_samples"] == 1
    assert result["code_samples"] == 1
    assert result["avg_lines_changed"] == 30
    assert result["additions"] == 20


def test_month_boundaries_partial_month_and_rollout_not_fabricated():
    rows = [
        record(1, created="2026-03-01T00:00:00Z", merged="2026-03-31T23:59:59Z"),
        record(2, created="2026-04-01T00:00:00Z", merged="2026-04-01T00:00:00Z"),
        record(3, merged="2026-09-21T00:00:00Z"),
    ]
    result = report(rows)
    fixes = [r for r in result["monthly"] if r["segment"] == "Fixes"]
    assert len(fixes) == 7
    assert fixes[0]["month"] == "2026-03-01"
    assert fixes[0]["merged_prs"] == 1
    assert fixes[1]["merged_prs"] == 1
    assert fixes[-1]["end"] == "2026-09-20"
    assert fixes[-1]["merged_prs"] == 0
    assert result["rollout"]["after"] is None
    assert result["rollout"]["changes"] == {}


def test_estimate_only_tracked_new_post_launch_work_with_utc_dates():
    rows = [
        record(1, created="2026-09-20T23:59:59Z", merged="2026-09-22T00:00:00Z"),
        record(2, created="2026-09-21T00:00:00Z", merged="2026-09-22T00:00:00Z"),
        record(3, created="2026-09-21T00:00:00Z", merged="2026-09-22T00:00:00Z"),
        record(4, created="2026-09-21T00:30:00+01:00", merged="2026-09-22T00:00:00Z"),
    ]
    result = report(rows, end=date(2026, 9, 22), tracked={1, 2, 4})
    assert result["estimate"]["eligible_prs"] == 1
    assert result["rollout"]["days"] == 2
    assert result["rollout"]["before"]["start"] == "2026-09-19"
    assert result["rollout"]["before"]["end"] == "2026-09-20"
    assert result["rollout"]["after"]["start"] == "2026-09-21"


def test_metric_changes_require_complete_samples_not_just_enough_samples():
    rows = [
        record(i, commits_count=2, rework_commits=1, additions=10, deletions=10) for i in range(6)
    ]
    rows += [
        record(
            i + 6,
            created="2026-03-01T00:00:00Z",
            merged="2026-03-10T00:00:00Z",
            commits_count=4,
            rework_commits=2,
            additions=20,
            deletions=20,
        )
        for i in range(6)
    ]
    result = report(rows)
    assert result["changes"]["avg_commits"] == -50
    assert result["changes"]["avg_rework"] == -50
    rows[0]["commits_count"] = None
    result = report(rows)
    assert result["current"]["commits_samples"] == 5
    assert result["changes"]["avg_commits"] is None
    assert result["changes"]["avg_rework"] == -50


def test_bot_filter_can_select_bot_authored_features():
    result = analyze(
        [record(1, author="other[bot]", title="feat: charts", labels=[]), record(2)],
        STATUS,
        end=date(2026, 9, 20),
        days=30,
        baseline_end=date(2026, 3, 20),
        kind="bot",
    )
    assert result["current"]["merged"] == 1
    assert result["rows"][0]["number"] == 1
    assert result["impact"]["categories"][2]["current"]["merged_prs"] == 1


def test_queued_or_failed_tracked_work_never_earns_effort_credit():
    row = record(1, created="2026-09-21T00:00:00Z", merged="2026-09-22T00:00:00Z")
    result = impact_report(
        [row], STATUS, end=date(2026, 9, 22), days=30, baseline_end=date(2026, 3, 20), tracked={1}
    )
    assert result["estimate"]["eligible_prs"] == 0


def test_monthly_totals_sum_full_pr_durations_at_utc_merge_date():
    rows = [
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
    months = {row["month"]: row for row in report(rows)["monthly_totals"]}
    assert len(months) == 7
    assert months["2026-03-01"]["total_hours"] == 5
    assert months["2026-03-01"]["covered_total_hours"] == 5
    assert months["2026-03-01"]["merged_prs"] == 2
    assert months["2026-04-01"]["covered_total_hours"] == 2
    assert months["2026-05-01"]["covered_total_hours"] == 0
    assert months["2026-09-01"]["covered_total_hours"] == 0


def test_monthly_total_is_unknown_for_incomplete_history_or_invalid_duration():
    rows = [
        record(1, created="2026-03-01T00:00:00Z", merged="2026-03-01T02:00:00Z"),
        record(2, created="2026-03-02T00:00:00Z", merged="2026-03-01T01:00:00Z"),
    ]
    march = report(rows)["monthly_totals"][0]
    assert march["total_hours"] == 2  # Retain the measured subtotal for diagnostics.
    assert march["merge_samples"] == 1
    assert march["merged_prs"] == 2
    assert march["covered_total_hours"] is None
    missing = impact_report(
        [],
        {},
        end=date(2026, 9, 20),
        days=30,
        baseline_end=date(2026, 3, 20),
        tracked=set(),
    )
    assert all(row["covered_total_hours"] is None for row in missing["monthly_totals"])


def test_bounded_calendar_periods_clip_both_ends_and_partition_selected_prs():
    rows = [
        record(n, created="2026-08-01T00:00:00Z", merged=f"{day}T12:00:00Z")
        for n, day in enumerate(
            ["2026-08-30", "2026-08-31", "2026-09-01", "2026-09-06", "2026-09-07"], 1
        )
    ]
    result = impact_report(
        rows,
        STATUS,
        end=date(2026, 9, 6),
        days=7,
        baseline_end=date(2026, 3, 6),
        tracked=set(),
        bounded=True,
    )
    monthly = [r for r in result["monthly"] if r["segment"] == "Fixes"]
    weekly = [r for r in result["weekly"] if r["segment"] == "Fixes"]
    assert [(r["start"], r["end"], r["merged_prs"]) for r in monthly] == [
        ("2026-08-31", "2026-08-31", 1),
        ("2026-09-01", "2026-09-06", 2),
    ]
    assert [(r["start"], r["end"], r["merged_prs"]) for r in weekly] == [
        ("2026-08-31", "2026-09-06", 3)
    ]
    assert sum(r["total_hours"] or 0 for r in monthly) == result["current"]["total_hours"]
    assert sum(r["total_hours"] or 0 for r in weekly) == result["current"]["total_hours"]
