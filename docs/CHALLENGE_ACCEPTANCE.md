# Take-home acceptance and demo plan

Reviewed against Asmar’s original assignment, as supplied by Nasrudin. Snapshot: 21 September 2026. Working code, live provider execution, published evidence and the presentation are separate acceptance items.

## Criteria

| Assignment requirement | Implementation and evidence | Status |
| --- | --- | --- |
| Fork Superset and create selected issues | [Fork](https://github.com/Nasdin/superset), [MySQL issue #1](https://github.com/Nasdin/superset/issues/1), [autonomously discovered issue #3](https://github.com/Nasdin/superset/issues/3) | Implemented and real issues created |
| Event-driven Devin automation | Signed issue/PR webhook at the public domain; durable deduplication; periodic recovery; saved discovery cadence and manual intake | Real webhook delivery verified; scheduled discovery produced #3 |
| Programmatically manage Devin sessions | Organization API v3 creates correlated repair, discovery, dependency and fresh validation sessions; bounded session/ACU limits; uncertain outcomes hold dispatch | Real repair and discovery sessions completed |
| Successfully remediate selected issues | [PR #2](https://github.com/Nasdin/superset/pull/2) fixes #1; [PR #5](https://github.com/Nasdin/superset/pull/5) fixes #3 | Both implementation PRs exist; independent proof below applies to #2/#4 only |
| Independent working-system evidence | [Integration PR #4](https://github.com/Nasdin/superset/pull/4), exact SHA `7c5857dc4d2acb3ce324a25681dbd41cedada7da`; fresh [Devin validator](https://app.devin.ai/sessions/cce0a57c5e0a4fc7ac58df0884d10cbb) | Actual browser, database, API, regression and coverage artifacts inspected; v2 manifest passes gate policy |
| Observability for engineering leaders | [Live workspace](https://superset-devin.nasrudinsalim.com): Analytics, Workflows, Release gates, Learning, Operations | Live data, status/error signals, candidate provenance, provider links and delivery receipts |
| Public Docker solution with README | [Solution repository](https://github.com/Nasdin/superset-auto-engineering), root README, Compose/Postgres/Superset and optional SQLite setup | Available |
| Loom link within five minutes | Outline below | **Still required. Not recorded or submitted.** |

## What the real validation proves

Devin built the integrated candidate in its own isolated VM with Superset 6.1.0, SQLGlot 28.10.0, Postgres, Redis and MySQL 8.0.46. The baseline failed six of nine sub-day bucket cases. The candidate passed all nine direct database checks, returned expected rows through SQL Lab and chart APIs, and displayed correct buckets in Explore and a reloaded dashboard. The report includes actual curl commands/status/results, three screenshots, a browser recording, service/database logs, test output and coverage JSON.

The broad regression run reports **1,990 passed, three skipped**. Coverage for `superset/db_engine_specs/mysql.py` is **88/110 lines (80%)** and **9/20 branches (45%)**; these are scoped counts, not whole-repository coverage. This is readiness for human review, not an automatic merge or proof every Superset feature is correct.

PR #5’s independent validation and [Dependabot PR #6](https://github.com/Nasdin/superset/pull/6) have separate lifecycles. Do not present their in-progress work as passed. The [second integration PR #7](https://github.com/Nasdin/superset/pull/7) tracks #5.

## Product story

**Analytics explains the problem:** compare fix, feature and bot work across merge delay, commits, review rework and changed code, with monthly/rolling windows and the 21 September rollout marker. Estimated effort saved remains an explicit scenario. No historical before/after comparison can establish a new system’s causal impact on launch day.

**Workflows explains the work:** scheduled discovery, issue/PR events and manual intent enter visible lanes, with the underlying Devin session and durable state transitions. Dependabot and autonomous patches remain separate work types.

**Release gates earns approval:** reviewers inspect exact-revision evidence and independently executed checks directly in the PR and workspace. Superset BI powers analytics; a different candidate Superset runtime provides validation evidence.

**Learning shows reuse:** durable observations become scoped Devin Knowledge, then appear in later session context snapshots with their outcomes. This is observable memory reuse, not training the model or claiming every supplied lesson was successfully applied.

## Five-minute Loom outline

| Time | Show | Say |
| --- | --- | --- |
| 0:00–0:40 | Analytics, upstream/fork selector | Engineers lose time to repetitive fixes and dependency reviews; the missing piece is credible proof that the integrated revision works. Explain the actual baseline metrics and their limits. |
| 0:40–1:25 | Schedules & triggers, workflow lane, original issue | Show webhook/schedule/manual entry points and the same durable queue. Point to the real issue → Devin → PR chain. |
| 1:25–2:25 | PR #4 evidence reply, screenshot, curl output, tests | Show the exact SHA, baseline failure and candidate success. Explain why a fresh validator and real Superset runtime matter. |
| 2:25–3:20 | Source: worker, providers, validation, outbox | Explain bounded execution, idempotency, unknown outcomes, current-SHA checks and readback-confirmed publication. FastAPI/React/Postgres/Compose keep the system maintainable. |
| 3:20–4:05 | Learning, later session context; Dependabot lane | Devin can inspect, diagnose, edit, run services and interact with the browser. Memory transfers observations into later work; it does not itself prove improvement. |
| 4:05–4:45 | Analytics trends and Operations | Explain next steps: more repaired/validated cases, measured review effort, stronger isolation/retention and customer-specific policy. Mention the single-host demo limit and human merge boundary. |
| 4:45–5:00 | Public repos and live app | Close with the concrete working result and where evaluators can inspect it. Submit a Loom link, not an MP4 file. |
