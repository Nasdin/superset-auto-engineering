# Verification record

Verified locally on 2026-09-20. This record distinguishes implementation checks, actual baseline runtime evidence, and the still-unverified paid workflow.

## Application and orchestration

- Production TypeScript/Vite build and Docker image build passed. API container is healthy on loopback port 8000; durable worker is running with bounded dispatch enabled after take-home authentication.
- Backend pytest: **57 passed**. Coverage includes duplicate intake, atomic single-flight claiming, uncertain creation, polling outages, budget reservation, fresh-validator identity, exact SHA, contradictory or missing evidence, durable report outbox and stale evidence.
- Lost-response simulations after GitHub branch, merge and PR creation resume with exactly one of each mutation and preserve validation capacity. These are provider-contract simulations, not real PRs.
- Playwright dashboard: **3 passed**. Evidence and demo-review flows, navigation/search/mobile width, API failure and actual Live operations configuration/ledger are exercised.
- Restricted gateway on loopback 8001: overview path 404, unsigned webhook 401, signed issue event accepted, duplicate delivery deduplicated into the existing job. That local ingress test is retained separately from the subsequent real delivery proof below.
- Existing credentials were checked against publishable text files; no configured secret values were found. Runtime environment files are excluded from Git and Docker build context.

## Actual Superset baseline

- Exact source: `c37118edd0146019ab0ae4ae1a97a597cb56c88e`, release branch `6.1`.
- Built from that checkout, with an image label retaining the SHA. Isolated PostgreSQL, Redis, MySQL, Superset and Celery stack started; app and worker health checks are healthy.
- Browser test: **1 passed**. Actual validator login → SQL Lab → query synthetic MySQL fixture → assert `fixture_count=3` and `total_value=6`.
- The browser check initially found a missing `MySQLdb` dependency. The runtime image now includes the baseline-pinned `mysqlclient==2.2.6`; the same query passed after rebuilding.
- Real SQL Lab screenshot was visually inspected. The passing video is `evidence/superset-baseline.webm`. Artifact SHA-256 hashes and runtime image ID are in `evidence/baseline-manifest.json`.
- The original time-grain defect is separately reproduced against MySQL 8.0.46 after SQLGlot 28.10.0 rewriting: **6 of 9 checks fail**. This is intentionally failing baseline evidence, not a regression-test success.

## External state and outstanding proof

Real fork issue: https://github.com/Nasdin/superset/issues/1. Target branch `cognition-release-6.1` is present. The durable repair job started Devin session `e9b26529705f4aa3bdcded5fa85e5a43` in Asmar DE Takehome. The API and browser both confirmed it was working on issue #1 at the pinned baseline. Final cost and repair acceptance remain pending.

Organization-scoped API authentication returned HTTP 200. Not yet proved: completed Devin repair, a real repair/integration PR, fresh independent validation of a repaired candidate, provider artifact ingestion for a repaired candidate, Slack delivery, or a real scheduled discovery run. A temporary signed webhook tunnel is active; it does not expose the dashboard or Superset. The goal remains active.

The five original dashboard pages use labeled fixtures. The generated mockup is a design reference. Neither those fixtures nor the locally recorded baseline video qualifies a repaired release for approval. No approval, release merge or deployment has occurred.

Dependency warnings from Starlette/httpx and AnyIO remain; there are no backend test failures. Human review is performed on the resulting GitHub evidence; authenticated multi-user review and automatic merge are outside the current implementation.

## GitHub evidence delivery and real event verification

- Baseline screenshot, video, reproduction results and manifest published to the separate `cognition/evidence/baseline-c37118ed` branch at `4277b0fee4e409618e9e189124f34c43b9ee75f7`. All four public URLs return 200; screenshot/video/reproduction bytes match local artifacts.
- The control plane's outbox posted [issue comment 5744078328](https://github.com/Nasdin/superset/issues/1#issuecomment-5744078328), then fetched it and checked its exact body and target. Repeating the publication request left one comment. The report explicitly says baseline qualification, not a fix or approval.
- GitHub webhook `681964250` sends issue events through a temporary Cloudflare Quick Tunnel into only the signed endpoint. Public dashboard access returns 404; an unsigned event returns 401.
- A real `issues/labeled` delivery was acknowledged with 200 and the existing repair job ID; its GUID is persisted in SQLite. GitHub redelivery returned `duplicate` with 200. The original issue label set was restored after testing.
- Evidence records: `evidence/github-baseline-publication.json` and `evidence/github-webhook-live.json`. No paid Devin session started during these checks.
- Receipt fault tests include process restart, readback outage, frozen Slack destination, malformed mutation responses and Slack's explicitly ambiguous internal errors. Acknowledged posts are never resent by readback recovery.

## Public repository and authorized Slack destination

- Created https://github.com/Nasdin/superset-auto-engineering as PUBLIC and pushed `main`; remote visibility and commit `e335f4773cd0d9b3761d24ed665b1177058d3638` were read back through GitHub.
- Scanned 89 historical Git blobs before publication against locally configured secret values and common credential patterns; no matches. Original private remote remains available; `public` is the new delivery remote.
- Fresh application checks after configuration: 47 backend tests passed and production frontend build passed.
- Nasrudin workspace `T0C2NTV3Z39`, #tech `C0C2NTYCPTR` was verified in the browser. The dedicated bot manifest requests only `chat:write`; installation awaits the browser tool's required action-time confirmation. No Slack report has been sent yet.

## First real repair and lifecycle correction

- Devin opened https://github.com/Nasdin/superset/pull/2 at `0d0c15d181379d8e1426ba69d7201a05a4a438f7`, targeting `cognition-release-6.1`. The PR reports 54 passing MySQL unit tests and 995 passing engine-spec tests (3 skipped), with baseline failures recorded separately.
- Independently reran the original nine-case matrix from the fetched PR SHA against local MySQL 8.0.46 and SQLGlot 28.10.0: **9/9 passed**. Raw results: `evidence/mysql-repair-pr2.json` (the reproduction script's `baseline_sha` field identifies the supplied PR reference). This is database-expression verification, not browser or integrated-release approval.
- Actual provider final handoff contained a PR and no blocker but returned `running/waiting_for_user`, so the initial worker parked it for attention. Future schemas require `task_complete`; an idle handoff is accepted only for literal boolean true and still goes through the same PR/evidence checks. Active work, approval waits, suspended sessions, missing/false/truthy substitutes and repair blockers remain excluded.
- The initial legacy-schema handoff was manually reviewed and audited with its exact session/status/PR SHA, then processed through `finish_repair`. No completion flag was invented and no validation was bypassed.
- Fresh verification after the correction: **57 backend tests passed**, production Docker build passed, containers restarted with the durable ledger retained. Slack bot installation still awaits confirmation.

## Dependabot and product story — 2026-09-20, latest checkpoint

This checkpoint supersedes older implementation counts and configuration notes above; those sections retain the historical sequence.

- Backend: **135 tests passed**, 84.25% measured coverage; Ruff clean. Frontend: **11 browser/API tests passed**, one optional external Superset baseline test skipped; TypeScript/Vite production build passed. Fixture-based checks are not candidate acceptance.
- Nine-slide deck: package/layout validation passed, four editable native charts with embedded data workbooks, all nine rendered slides visually inspected. Data totals reconcile to 772 August PRs and 120 pinned commits. The 12-PR sample explicitly identifies PR #42053 as potentially truncated at 100 commits.
- Deployed Dependabot and PR evidence pages show actual fork PRs. The former shows bot PR #6 at SHA `5bc5e8a8bc241081fb30a992e94b96aeaf368aa8`, one queued job, zero accepted artifacts, and the current PR #4 budget hold. Component PRs also link to the integration validation containing them, labeled with the combined candidate SHA.
- Real Dependabot version updates enabled on the fork with a one-PR PyJWT rollout. Existing signed webhook extended to `pull_request` without losing `issues` or its secret. GitHub delivery `8a394660-b4ac-11f1-980e-4b144178780c` was accepted with HTTP 200 and the existing queued job ID. No duplicate run was created.
- The control-plane worker and analytics process were rebuilt with persisted data retained. A SQLite backup was taken before rollout. No session cap was raised; the suspended independent validator remains an explicit live acceptance blocker.
- See [Dependabot configuration and acceptance boundary](DEPENDABOT.md) and [the live dashboard capture](screenshots/dependabot-pr-6.png). The capture shows queued work, not successful validation.

## Learning and autonomous patches — 2026-09-20

- Added native organization Knowledge publication/readback and explicit per-dispatch memory snapshots, a Learning & memory page, and four workflow lanes.
- Restored the existing completed discovery's structured result from its original Devin session and linked its existing repair job; no issue, PR or session was created by recovery.
- Live provider readback confirmed three project-owned Knowledge notes (one discovery, two reported implementations). All remain explicitly unverified observations. Zero sessions have yet been dispatched using tracked memory; four existing paid sessions remain in the ledger.
- The independent validator for PR #4 remains `needs_attention` / `usage_limit_exceeded`. This holds new scans, PR fixes and dependency work. Limits remain 10 ACU per session and six sessions total. No memory-assisted end-to-end validation or improvement claim is made.
- Backend: 155 tests passed, 84.79% coverage. Includes uncertain create/readback recovery, stale note retirement, ambiguous retirement without phantom session usage, scope changes, immutable context, scan/webhook race recovery and duplicate PR pipeline prevention.
- Frontend: production build passed; 13 browser tests passed, one optional external Superset test skipped. Learning filters, evidence links, empty history, mobile layout and workflow lanes were exercised.
- Real browser inspection showed three native notes, the existing usage blocker, and scan → repair PR #5 lineage in the autonomous lane. Screenshots are in `docs/screenshots/learning-memory.png` and `docs/screenshots/workflow-lanes.png`.

- Corrected the legacy health endpoint: `/api/health` checks the live ledger and reports live mode plus the automation switch; demo health remains explicitly under `/api/demo/health`.
