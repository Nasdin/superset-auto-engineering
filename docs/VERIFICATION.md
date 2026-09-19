# Verification record

Verified locally on 2026-09-20. This record distinguishes implementation checks, actual baseline runtime evidence, and the still-unverified paid workflow.

## Application and orchestration

- Production TypeScript/Vite build and Docker image build passed. API container is healthy on loopback port 8000; durable worker is running with dispatch disabled.
- Backend pytest: **33 passed**. Coverage includes duplicate intake, atomic single-flight claiming, uncertain creation, polling outages, budget reservation, fresh-validator identity, exact SHA, contradictory or missing evidence, durable report outbox and stale evidence.
- Lost-response simulations after GitHub branch, merge and PR creation resume with exactly one of each mutation and preserve validation capacity. These are provider-contract simulations, not real PRs.
- Playwright dashboard: **3 passed**. Evidence and demo-review flows, navigation/search/mobile width, API failure and actual Live operations configuration/ledger are exercised.
- Restricted gateway on loopback 8001: overview path 404, unsigned webhook 401, signed issue event accepted, duplicate delivery deduplicated into the existing job. This is a local ingress test, not a real GitHub webhook delivery.
- Existing credentials were checked against publishable text files; no configured secret values were found. Runtime environment files are excluded from Git and Docker build context.

## Actual Superset baseline

- Exact source: `c37118edd0146019ab0ae4ae1a97a597cb56c88e`, release branch `6.1`.
- Built from that checkout, with an image label retaining the SHA. Isolated PostgreSQL, Redis, MySQL, Superset and Celery stack started; app and worker health checks are healthy.
- Browser test: **1 passed**. Actual validator login → SQL Lab → query synthetic MySQL fixture → assert `fixture_count=3` and `total_value=6`.
- The browser check initially found a missing `MySQLdb` dependency. The runtime image now includes the baseline-pinned `mysqlclient==2.2.6`; the same query passed after rebuilding.
- Real SQL Lab screenshot was visually inspected. The passing video is `evidence/superset-baseline.webm`. Artifact SHA-256 hashes and runtime image ID are in `evidence/baseline-manifest.json`.
- The original time-grain defect is separately reproduced against MySQL 8.0.46 after SQLGlot 28.10.0 rewriting: **6 of 9 checks fail**. This is intentionally failing baseline evidence, not a regression-test success.

## External state and outstanding proof

Real fork issue: https://github.com/Nasdin/superset/issues/1. Target branch `cognition-release-6.1` is present. One durable repair job is queued; zero Devin sessions and zero reported ACU through this app.

Not yet proved: take-home organization API authentication, paid Devin repair, a real repair/integration PR, fresh independent validation of a repaired candidate, provider artifact ingestion, GitHub evidence comment delivery, Slack delivery, or a real scheduled discovery run. There is no public webhook tunnel. The goal remains active.

The five original dashboard pages use labeled fixtures. The generated mockup is a design reference. Neither those fixtures nor the locally recorded baseline video qualifies a repaired release for approval. No approval, release merge or deployment has occurred.

Dependency warnings from Starlette/httpx and AnyIO remain; there are no backend test failures. Human review is performed on the resulting GitHub evidence; authenticated multi-user review and automatic merge are outside the current implementation.
