# Why this product: from repository activity to reviewable evidence

We started with a practical question: what recurring Superset work can an autonomous engineer complete, and what proof would make a senior engineer willing to merge it? The observations favor bounded dependency and regression work, followed by independent validation. The data does not demonstrate hours saved or a causal effect from this system.

## 1. Measure the repository before choosing the workflow

The committed public SQLite snapshot contains 11,700 upstream PR records. It was collected on 20 September 2026 with a completed coverage horizon beginning 21 September 2024. We use UTC merge-date cohorts and only completed days. September is shown separately because it is incomplete.

| Merge cohort | Merged PRs | Dependencies | Fixes | Features | Other | Reverts | Dependabot authors |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-06-01–2026-06-30 | 767 | 289 | 317 | 55 | 104 | 2 | 248 |
| 2026-07-01–2026-07-31 | 854 | 281 | 331 | 122 | 119 | 1 | 251 |
| 2026-08-01–2026-08-31 | 772 | 301 | 315 | 74 | 81 | 1 | 267 |
| 2026-09-01–2026-09-19 | 528 | 181 | 250 | 37 | 60 | 0 | 160 |

In August, dependency and fix signals account for 616/772 PRs (79.8%). Dependabot authored 267/772 (34.6%). Dependency changes total 301 because people also submit dependency work. These are observable work signals, not verified estimates of effort.

## 2. Make the classification inspectable

The shared classifier applies this precedence: revert/rollback title → dependency signal → fix signal → feature signal → other. Dependency signals include the exact Dependabot author, dependency labels and dependency/bump title terms. Fixes use fix/bugfix title prefixes or bug labels. Features use feat/feature prefixes or feature/enhancement labels. The first matching rule wins. Current titles and labels can differ from those at merge time; mixed-scope PRs are reduced to one category.

Dependabot provenance is separately retained as `author == "dependabot[bot]"`. Operational intake additionally verifies GitHub's author type is `Bot`. Other bots are not treated as Dependabot.

The [August PR CSV](analysis/august-pr-classification.csv) contains all 772 classified PRs with links. The [commit CSV](analysis/commit-classification.csv) contains 120 linked, classified commits. Commit classification uses title and author only: PR labels are unavailable in that sample.

## 3. Cross-check at the commit level

The first 120 commits returned by GitHub at pinned master SHA `4511c1381930ec53cd74c1e25c3ad4397768e2b4` contain 59 fix signals, 41 dependency signals, eight feature signals and 12 other commits. Thirty-nine are Dependabot-authored. This sample contains no merge commits. It is a recent API-order sample, not the total for a calendar interval.

A commit is not an hour of work. Squash merges compress a PR into a single commit; rebases and force pushes can replace prior history. The [raw commit snapshot](analysis/commits.json) preserves SHA, parents, author, timestamp, title and URL.

## 4. Inspect retained follow-up history

We chose three PRs per stratum (Dependabot, fix, feature, other) from August. Within each stratum, records are sorted by number and sampled with Python `random.Random(42)`. This deliberately balanced 12-PR sample is not representative of the population. Five retain more than one commit; seven have a retained commit with a committer timestamp after PR creation. A later timestamp may reflect a rebase or branch synchronization, not necessarily a human correction.

| Stratum | PR | Retained commits | Dated after opening | Merge commits |
|---|---|---:|---:|---:|
| dependabot | [#42777 chore(deps): bump selenium from 4.45.0 to 4.46.0](https://github.com/apache/superset/pull/42777) | 2 | 1 | 0 |
| dependabot | [#42680 chore(deps): bump the storybook group in /docs with 2 updates](https://github.com/apache/superset/pull/42680) | 1 | 0 | 0 |
| dependabot | [#43106 chore(deps-dev): bump tsx from 4.23.7 to 4.23.9 in /superset-frontend](https://github.com/apache/superset/pull/43106) | 1 | 0 | 0 |
| fix | [#42596 fix(filters): sort numeric filter values numerically, not lexicographically (#36775)](https://github.com/apache/superset/pull/42596) | 4 | 4 | 0 |
| fix | [#41589 fix(calendar): clean up d3-tip tooltips](https://github.com/apache/superset/pull/41589) | 18 | 18 | 10 |
| fix | [#42920 fix(import): isolate per-tag import in a SAVEPOINT to avoid poisoned session (#42912)](https://github.com/apache/superset/pull/42920) | 4 | 2 | 1 |
| feature | [#42053 feat: Color Picker replaces the color selection drop-down list in conditional formatting](https://github.com/apache/superset/pull/42053) | 100 | 29 | 69 |
| feature | [#35825 feat(docs): add documentation for usage of minio or other s3 compatible service as a cache backend or celery results backend](https://github.com/apache/superset/pull/35825) | 1 | 1 | 0 |
| feature | [#42940 feat(build): reinstate `no-restricted-imports` lint rule for `lodash`](https://github.com/apache/superset/pull/42940) | 1 | 0 | 0 |
| other | [#42476 perf(charts): reuse datasource in query context](https://github.com/apache/superset/pull/42476) | 1 | 0 | 0 |
| other | [#40635 chore(i18n): update french po file to match latest pot file version](https://github.com/apache/superset/pull/40635) | 1 | 1 | 0 |
| other | [#42943 docs(mcp): add update_dashboard to write-tools enumeration](https://github.com/apache/superset/pull/42943) | 1 | 0 | 0 |

All retained commit URLs and dates are in [the sample JSON](analysis/pr-commit-sample.json). The API fetch is capped at 100 commits per sampled PR and marks possible truncation; **PR #42053 reached that limit and may be truncated**. Its commit counts are lower bounds. This refresh uses a new documented sample; it does not pretend to reproduce every example from the earlier exploratory conversation.

## 5. Compare equal windows over time

Recent: **21 August–19 September 2026**. Six calendar months earlier: **18 February–19 March 2026**. Both windows contain 30 complete UTC days. PRs enter a cohort by merge date; duration is `merged_at - created_at` in elapsed calendar hours. Closed unmerged PRs are excluded, so this view has survivor bias. It does not capture the still-open backlog, active coding time or review time separately.

| Work signal | Recent N | Earlier N | Recent median hours | Earlier median hours | Recent P75 | Earlier P75 |
|---|---:|---:|---:|---:|---:|---:|
| all | 806 | 333 | 25.28 | 25.32 | 138.00 | 163.53 |
| dependency | 274 | 121 | 7.53 | 11.74 | 12.87 | 31.31 |
| fix | 371 | 140 | 78.30 | 69.30 | 218.05 | 236.92 |
| feature | 73 | 41 | 98.31 | 151.72 | 371.23 | 392.63 |

All-work medians are almost unchanged, while category medians move differently. A changing work mix can obscure or manufacture an apparent improvement. The dashboard therefore provides repository, author, label, base branch, work signal and tracked-work filters, equal window lengths, N, median, P75 and coverage checks. P75 uses the nearest-rank definition. Incomplete coverage or fewer than five observations suppresses the improvement percentage.

**No causal improvement is attributed to Cognition.** To evaluate it, collect comparable treated/untreated PRs, track exact intervention timing, review effort, rework, regressions and accepted evidence, and report uncertainty. Upstream history is a baseline; the fork is the execution environment.

## 6. Turn the observations into a workflow

Dependencies provide recurring, bounded incoming work; regression fixes have behavior that can be reproduced. Devin prepares an update or repair, then a fresh session starts Superset and validates the exact candidate. The product packages the screenshots, video, logs and test output where an engineer reviews the PR. [The Dependabot explainer](DEPENDABOT.md) describes event intake, deduplication, scope, budgets and the live acceptance gap.

## Reproduce the analysis

From the repository root:

```sh
backend/.venv/bin/python scripts/analyze_repository.py
# Optional: re-fetch retained commits for the documented 12-PR sample using authenticated gh.
backend/.venv/bin/python scripts/analyze_repository.py --fetch-sample
```

Offline reproduction reads the committed public metadata database and JSON snapshots, and regenerates `summary.json` and the CSVs. The 120-commit sample is fixed at its recorded SHA; it is not silently refreshed by this command. No live automation ledger, credentials or private session data is included in the analysis files.

Sources: [Apache Superset PR history](https://github.com/apache/superset/pulls), [pinned master revision](https://github.com/apache/superset/commit/4511c1381930ec53cd74c1e25c3ad4397768e2b4), and the per-PR/per-commit links in the accompanying snapshots. API methodology: [List repository commits](https://docs.github.com/en/rest/commits/commits#list-commits) and [List PR commits](https://docs.github.com/en/rest/pulls/pulls#list-commits-on-a-pull-request).
