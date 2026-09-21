# Engineering impact

Two generated concepts guided this iteration:

- [Impact overview](analytics-impact-concept.png): compact metrics, category comparison, rollout annotation and explicit estimate assumptions.
- [Metric trends](analytics-metrics-concept.png): four focused charts for delivery, commits, rework and code volume.

Both are **illustrative design concepts**, generated with the built-in image tool, not evidence of actual results. The implementation uses real GitHub records and Apache Superset. The generated second concept accidentally labels the year 2024; the implemented rollout date is **21 September 2026 UTC**. The first concept's illustrative post-launch points are not implemented.

Prompt briefs: a restrained off-white engineering dashboard with a compact navigation, teal Fixes, blue Features, amber Bots; repository and time controls; commits/PR, median merge hours, post-review commits and added/removed lines; four monthly trends with a dotted 21 September rollout marker; empty post-launch data; a comparison table and an explicitly assumption-based time-saved model. No illustrated values are seeded into the application.

## What the numbers mean

All cohorts use the UTC merge date. Fixes and Features use existing title/label signals. A GitHub bot author takes precedence in the **Bots** segment, so rows cannot double-count. **Documentation, Dependencies, Refactoring, Tests, Build & CI, Performance, Releases, Reverts and Maintenance** retain their specific meanings. Explicit title intent wins over broad labels. Only genuinely ambiguous metadata is flagged **Needs classification**; reviewed PR exceptions include a source and reason. Bot accounts and ledger-tracked Devin work are separate dimensions.

| Measure | Definition | Limits |
| --- | --- | --- |
| Commits per PR | Mean final PR commit count | Rebases/force-pushes can hide earlier work |
| Hours to merge | Median elapsed hours, PR opening to merge | Waiting time is not working time |
| Rework after review | Mean commits dated after the first submitted human non-author review, through merge | A proxy; final history cannot recover discarded commits |
| Code written/removed | Final additions and deletions; mean total changed lines per PR | Includes generated files; volume is not quality or productivity |
| Estimated time saved | Eligible tracked merged PRs × (assumed manual effort − assumed human oversight) | A scenario, not observed labour savings or a causal estimate |

Every measure exposes its own denominator. Unknown values remain missing; zero rework requires complete review collection. GitHub caps PR commit lists at 250, so larger histories retain commit/line totals but cannot establish rework through this endpoint.

Changes require complete date coverage, every PR measured for the metric, and at least five observations in both windows. Current-versus-baseline comparisons support previous rolling windows, six months earlier, or custom dates. Monthly charts show seven calendar months; the final month is partial. Rolling charts sample the selected window weekly. A chart-only null point makes the rollout marker visible without inventing observations.

The launch comparison uses equal, non-overlapping windows before and after 21 September, bounded by the selected window length. Before the first completed post-launch UTC day, it remains empty. The date does not imply that upstream Apache Superset adopted this system. Time-saved eligibility additionally requires a completed implementation/preparation session and that the tracked PR was opened on or after launch; incomplete coverage withholds the model.

## Data collection

The hourly analytics process imports public PR metadata and performs a bounded detail backfill across months/categories. It reads GitHub PR details, reviews and commits; it never dispatches Devin. Progress is stored under `sync_status.enrichment`. Partial samples are visibly provisional. Old results survive errors; changed PR snapshots are remeasured. Run a larger bounded backfill with:

```sh
docker compose exec cognition python -m app.analytics.enrichment \
  --repository apache/superset --max-prs 600 --max-requests 2400
```

This uses the existing private `GITHUB_TOKEN` and database configuration. It stops at the rate-limit reserve. Do not run multiple backfills against the same repository concurrently.

## Public acceptance

Deployed revision `212c7804153fc59527f537e8d0d1f7c61c3db9b9` to the existing Sydney Lightsail host on 21 September 2026 Singapore time (20 September UTC). [Code quality CI](https://github.com/Nasdin/superset-auto-engineering/actions/runs/35525035803) passed. The backend suite passed 228 tests with 86.06% branch coverage; the frontend suite passed 15 tests with three explicit environment-dependent skips. A separate real Superset test passed locally and against the public HTTPS deployment.

The public test checked all five chart responses, monthly merge-metric parity with the API, monthly/rolling switching, 60-day windows, bot filtering, upstream/fork isolation, native rollout annotations and stacked charts at 390px. [Desktop screenshot](../screenshots/engineering-impact-desktop.png), [mobile screenshot](../screenshots/engineering-impact-mobile.png), and [API/authentication receipt](../analysis/engineering-impact-verification.json) are from this deployment.

The initial detailed backfill imported 600 upstream PRs and four fork PRs. The hourly importer continues from persisted progress. Screenshots and receipts are point-in-time observations; counts can change during import. No post-launch improvement or measured labour savings is claimed before data exists. The workflow worker and its existing execution holds were not changed by this analytics deployment.

The leading category-total chart sums creation-to-merge hours per work type and UTC merge month. It partitions the all-work total; bots never also count in a human work category. Incomplete history or invalid durations remain gaps.
