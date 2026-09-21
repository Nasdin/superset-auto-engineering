"""Engineering measures with explicit denominators and no inferred labour savings."""

from datetime import UTC, date, timedelta
from statistics import mean, median

from .classification import CATEGORY_LABELS, SEGMENTS, category
from .metrics import cohort, covered, hours, months_before, timestamp

ROLLOUT_DATE = date(2026, 9, 21)


def is_bot(pr):
    return (pr.get("author_type") or "").lower() == "bot" or pr["author"].lower().endswith("[bot]")


def segment(pr):
    return "Bots" if is_bot(pr) else CATEGORY_LABELS[category(pr)]


def measure(rows):
    def values(key):
        return [pr[key] for pr in rows if isinstance(pr.get(key), (int, float)) and pr[key] >= 0]

    durations = [value for pr in rows if (value := hours(pr)) is not None]
    commits, rework = values("commits_count"), values("rework_commits")
    code = [
        pr for pr in rows if pr.get("additions") is not None and pr.get("deletions") is not None
    ]
    return {
        "merged_prs": len(rows),
        "merge_samples": len(durations),
        "commits_samples": len(commits),
        "rework_samples": len(rework),
        "code_samples": len(code),
        "median_hours": median(durations) if durations else None,
        "total_hours": sum(durations) if durations else (0 if not rows else None),
        "avg_commits": mean(commits) if commits else None,
        "avg_rework": mean(rework) if rework else None,
        "additions": sum(pr["additions"] for pr in code) if code else None,
        "deletions": sum(pr["deletions"] for pr in code) if code else None,
        "avg_lines_changed": mean(pr["additions"] + pr["deletions"] for pr in code)
        if code
        else None,
    }


def window(rows, status, end, days):
    bounds = {"start": (end - timedelta(days=days - 1)).isoformat(), "end": end.isoformat()}
    measured = measure(cohort(rows, end, days))
    complete = covered(status, bounds)
    return {
        **bounds,
        **measured,
        "covered": complete,
        "covered_total_hours": measured["total_hours"]
        if complete and measured["merge_samples"] == measured["merged_prs"]
        else None,
    }


def changes(current, baseline):
    result = {}
    for key, sample in (
        ("median_hours", "merge_samples"),
        ("avg_commits", "commits_samples"),
        ("avg_rework", "rework_samples"),
        ("avg_lines_changed", "code_samples"),
    ):
        complete = all(
            row["covered"] and row[sample] >= 5 and row[sample] == row["merged_prs"]
            for row in (current, baseline)
        )
        result[key] = (
            (current[key] / baseline[key] - 1) * 100
            if complete and baseline[key] and current[key] is not None
            else None
        )
    return result


def impact_report(rows, status, *, end, days, baseline_end, tracked, completed=None):
    completed = completed or set()
    current = window(rows, status, end, days)
    baseline = window(rows, status, baseline_end, days)
    grouped = {name: [] for name in SEGMENTS}
    for pr in rows:
        grouped[segment(pr)].append(pr)
    categories = []
    for name in SEGMENTS:
        selected = grouped[name]
        now = window(selected, status, end, days)
        before = window(selected, status, baseline_end, days)
        categories.append(
            {"segment": name, "current": now, "baseline": before, "changes": changes(now, before)}
        )
    monthly = []
    monthly_totals = []
    for offset in range(6, -1, -1):
        start = months_before(end.replace(day=1), offset)
        stop = min(months_before(start, -1) - timedelta(days=1), end)
        monthly_totals.append(
            {
                "month": start.isoformat(),
                **window(rows, status, stop, (stop - start).days + 1),
            }
        )
        for name in SEGMENTS:
            monthly.append(
                {
                    "month": start.isoformat(),
                    "segment": name,
                    **window(
                        grouped[name],
                        status,
                        stop,
                        (stop - start).days + 1,
                    ),
                }
            )
    # Symmetric, non-overlapping windows around launch; no post-launch data is invented.
    post_days = min(days, max(0, (end - ROLLOUT_DATE).days + 1))
    before = window(rows, status, ROLLOUT_DATE - timedelta(days=1), post_days or days)
    after = window(rows, status, end, post_days) if post_days else None
    eligible = [
        pr
        for pr in cohort(rows, end, days)
        if pr["number"] in tracked
        and pr["number"] in completed
        and timestamp(pr["created_at"]).astimezone(UTC).date() >= ROLLOUT_DATE
    ]
    return {
        "rollout_date": ROLLOUT_DATE.isoformat(),
        "current": current,
        "baseline": baseline,
        "changes": changes(current, baseline),
        "categories": categories,
        "monthly": monthly,
        "monthly_totals": monthly_totals,
        "rollout": {
            "before": before,
            "after": after,
            "days": post_days,
            "changes": changes(after, before) if after else {},
        },
        "estimate": {
            "eligible_prs": len(eligible),
            "covered": current["covered"],
            "by_segment": {name: sum(segment(pr) == name for pr in eligible) for name in SEGMENTS},
        },
    }
