"""Pure cohort calculations: UTC merge-date cohorts, elapsed calendar hours."""

import calendar
import math
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from statistics import median


def months_before(day: date, months=6):
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def category(pr):
    """Observable, mutually exclusive title/label signals, not semantic ground truth."""
    title = pr["title"].lower()
    labels = {label.lower() for label in pr["labels"]}
    if re.search(r"\brevert\b|\brollback\b", title):
        return "revert"
    if (
        pr["author"].lower() == "dependabot[bot]"
        or any(
            label in {"dependencies", ".dependency", "dependabot"}
            or label.startswith("dependencies:")
            for label in labels
        )
        or re.search(r"\b(deps|dependency|dependencies|bump)\b", title)
    ):
        return "dependency"
    if re.match(r"(fix|bugfix)(\b|\()", title) or labels & {
        "#bug",
        "bug",
        "fix",
        "bugfix",
        "type:bug",
    }:
        return "fix"
    if re.match(r"(feat|feature)(\b|\()", title) or labels & {"enhancement", "feature"}:
        return "feature"
    return "other"


def hours(pr):
    created, merged = timestamp(pr["created_at"]), timestamp(pr["merged_at"])
    return (
        (merged - created).total_seconds() / 3600
        if merged and created and merged >= created
        else None
    )


def bounds(end, days):
    return datetime.combine(
        end - timedelta(days=days - 1), datetime.min.time(), UTC
    ), datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC)


def cohort(pulls, end, days):
    start, stop = bounds(end, days)
    return [pr for pr in pulls if pr["merged_at"] and start <= timestamp(pr["merged_at"]) < stop]


def summarize(pulls, end, days):
    rows = cohort(pulls, end, days)
    values = sorted(value for pr in rows if (value := hours(pr)) is not None)
    return {
        "start": (end - timedelta(days=days - 1)).isoformat(),
        "end": end.isoformat(),
        "merged": len(rows),
        "sample_size": len(values),
        "excluded_invalid": len(rows) - len(values),
        "median_hours": median(values) if values else None,
        "p75_hours": values[max(0, math.ceil(len(values) * 0.75) - 1)] if values else None,
    }


def covered(status, summary):
    broad = bool(
        status.get("complete")
        and status.get("coverage_from", "9999") <= summary["start"]
        and status.get("last_success")
        and timestamp(status["last_success"]) >= bounds(date.fromisoformat(summary["end"]), 1)[1]
    )
    cursor = date.fromisoformat(summary["start"])
    stop = date.fromisoformat(summary["end"])
    months = {row["month"]: row for row in status.get("months", [])}
    while cursor <= stop:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        required = min(stop, next_month - timedelta(days=1)).isoformat()
        receipt = months.get(cursor.replace(day=1).isoformat())
        if receipt is not None:
            if (receipt.get("covered_through") or "") < required:
                return False
        elif not broad:
            return False
        cursor = next_month
    return True


def analyze(
    pulls,
    status,
    *,
    end,
    days,
    baseline_end,
    author="",
    label="",
    base="",
    kind="",
    tracked=None,
    completed=None,
    provenance="all",
    offset=0,
):
    from .impact import impact_report, is_bot

    tracked = tracked or set()
    selected = [
        pr
        for pr in pulls
        if (not author or pr["author"] == author)
        and (not label or label in pr["labels"])
        and (not base or pr["base"] == base)
        and (not kind or (is_bot(pr) if kind == "bot" else category(pr) == kind))
        and (provenance != "tracked" or pr["number"] in tracked)
        and (provenance != "untracked" or pr["number"] not in tracked)
    ]
    current = summarize(selected, end, days)
    baseline = summarize(selected, baseline_end, days)
    for item in (current, baseline):
        item["covered"] = covered(status, item)
    enough = current["sample_size"] >= 5 and baseline["sample_size"] >= 5
    change = None
    if current["covered"] and baseline["covered"] and enough and baseline["median_hours"] > 0:
        change = (current["median_hours"] / baseline["median_hours"] - 1) * 100
    trend = []
    for delta in range(182, -1, -7):
        point = summarize(selected, end - timedelta(days=delta), days)
        point["covered"] = covered(status, point)
        trend.append(point)
    merged = sorted(cohort(selected, end, days), key=lambda pr: pr["merged_at"], reverse=True)
    start, stop = bounds(end, days)
    opened = sum(start <= timestamp(pr["created_at"]) < stop for pr in selected)
    closed = sum(
        bool(pr["closed_at"] and not pr["merged_at"] and start <= timestamp(pr["closed_at"]) < stop)
        for pr in selected
    )
    return {
        "impact": impact_report(
            selected,
            status,
            end=end,
            days=days,
            baseline_end=baseline_end,
            tracked=tracked,
            completed=completed,
        ),
        "current": current,
        "baseline": baseline,
        "change_percent": change,
        "trend": trend,
        "opened": opened,
        "closed_unmerged": closed,
        "observed_open": sum(pr["state"] == "open" for pr in selected),
        "categories": dict(Counter(category(pr) for pr in merged)),
        "total_rows": len(merged),
        "offset": offset,
        "rows": [
            {
                **pr,
                "hours_to_merge": hours(pr),
                "category": category(pr),
                "tracked": pr["number"] in tracked,
            }
            for pr in merged[offset : offset + 50]
        ],
        "filters": {
            "authors": sorted({pr["author"] for pr in pulls}),
            "labels": sorted({label for pr in pulls for label in pr["labels"]}),
            "bases": sorted({pr["base"] for pr in pulls}),
        },
        "sync": status,
        "stored_prs": len(pulls),
    }
