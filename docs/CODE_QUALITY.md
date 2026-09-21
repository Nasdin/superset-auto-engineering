# Architecture and code quality

The original implementation had useful safety mechanisms (durable jobs, bounded sessions, a receipt-based outbox), but the engine owned intake, integration, evidence policy and rendering. The frontend similarly mixed pages, dialogs and network state. This made changes difficult to isolate and left important failure paths untested.

## Boundaries and patterns

| Boundary | Responsibility | Main files |
| --- | --- | --- |
| Application/runtime factories | Construct dependencies and register cleanup immediately; close HTTP and database pools on shutdown or partial startup failure | `backend/app/main.py`, `automation/runtime.py` |
| Provider port and adapter | Describe the external operations workflows need; implement them with HTTPX; allow fake providers in tests | `automation/ports.py`, `providers.py` |
| Repository | SQLAlchemy/Postgres transactions, durable identity, job claims, metrics and publication receipts | `automation/store.py` |
| Application services | Coordinate issue intake, bounded sessions, integration and validation | `engine.py`, `integration.py`, `validation.py` |
| Evidence policy | Pure acceptance rules for candidate SHA, independent sessions, checks and provider-confirmed artifacts | `evidence.py` |
| Report builder | Convert accepted/failed evidence into escaped, readable Markdown without external calls | `reports.py` |
| Transactional outbox | Store publication intent and receipts; reconcile acknowledged writes without resending | `outbox.py` |
| Frontend pages | Render typed page props; keep shared visuals separate | `frontend/src/pages/`, `components/` |
| Frontend request state | Centralize error handling, abort superseded requests, skip overlapping polls, stop on unmount | `api.ts`, `hooks/usePollingResource.ts` |

Use patterns where they provide a useful boundary. The runtime factory and report builder solve concrete construction and formatting problems. A hierarchy of abstract factories, generic repositories or fluent builders would add ceremony to this small application. Services use composition and structural provider interfaces; tests do not need an inheritance framework.

## Concurrency and resource budgets

FastAPI routes using synchronous SQLAlchemy or HTTPX are ordinary `def` handlers, which FastAPI executes in its bounded thread pool. The asynchronous webhook reads the request stream and then explicitly offloads durable intake. Authentication middleware also offloads its database lookup. Startup and cleanup use `contextmanager_in_threadpool` with an `ExitStack`, so dependencies acquired before a later startup failure are still closed. No request starts an in-process background task for durable Devin work; the separate worker owns that lifecycle.

This is intentional mixed concurrency. Changing a handler to `async def` while retaining synchronous I/O would block the event loop. If API throughput eventually justifies native async SQLAlchemy/HTTPX, migrate complete request paths and resource lifetimes together. The synchronous worker can remain independent. See [FastAPI's concurrency guidance](https://fastapi.tiangolo.com/async/).

Postgres application engines default to two retained connections plus one overflow connection, a five-second pool/connect timeout, a 30-second statement timeout and a five-second lock timeout. Idle transactions are terminated after 60 seconds. `pool_pre_ping` checks reused connections, but does not replay a failed transaction. `.env` exposes `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_CONNECT_TIMEOUT`, `DB_STATEMENT_TIMEOUT_MS` and `DB_LOCK_TIMEOUT_MS`; these are forwarded by Compose. Zero/unbounded pools or waits are rejected. SQLite retains its local adapter and lock timeout.

The API owns two engines; the worker and history-sync process own one each. These application pools can therefore consume **12 connections** at their defaults. Superset, administration, migrations and any extra processes need additional capacity. Every API replica multiplies its two pools; review the entire connection budget before increasing replicas or limits. The small host currently caps Postgres at 40 connections. See [SQLAlchemy's pool configuration](https://docs.sqlalchemy.org/en/20/core/pooling.html#connection-pool-configuration).

Superset's metadata engine is separately bounded at two retained plus one overflow connection. Chart engines use Superset's `NullPool`, with five-second connects and 30-second statement deadlines; three server threads match the metadata pool and bound concurrent chart work. Do not pass QueuePool-only arguments into these chart engines. Existing deployments must rerun the idempotent analytics bootstrap after changing persisted reporting-database connection settings.

Full-history Python analytics permits one analysis per API process. A second concurrent request is rejected immediately with `503` and `Retry-After: 2`, before loading repository records. The slot is released even when analysis fails; ordinary API traffic remains available. This protects the memory budget but deliberately limits throughput until analytics moves to SQL read models.

Provider HTTP clients also have bounded connection pools and separate connection/pool waits. Neither database middleware nor the browser transport automatically repeats mutations after a timeout. A timed-out response can follow a successful external action; retrieve the durable status and reconcile the existing intent first.

## Failure behavior in the API and browser

`/api/health/live` checks that the ASGI process responds without querying dependencies. `/api/health` remains the database-backed readiness check used by Compose. Database disconnections, lock/statement failures and pool exhaustion return a sanitized `503` with `code=database_unavailable`, `Retry-After` and an `X-Request-ID` matching the response body. Logs record the generated correlation ID and exception type, excluding SQL parameters and raw provider errors. Authentication fails closed during a database outage. These responses never claim that a write was rolled back at an external provider.

The frontend remains **React 19 + TypeScript + Vite** with strict type checking. Pages load lazily and have a keyed React error boundary so a failed view preserves navigation and sign-out. Shared requests have cancellation and a deadline; malformed gateway responses produce a readable error. Operator writes surface uncertain outcomes without automatic replay. Polls do not overlap, and stale responses cannot replace a newer selection.

Superset uses the official embedded SDK and server-issued, short-lived guest tokens scoped to the configured dashboard and a persisted filter selection. Its iframe lifecycle is separate from the parent application; token refresh, failed loading and rapid filter changes need their own recovery. The live chart test checks actual Superset query results against the reference analytics, repository isolation, cadence switching, rollout annotations and mobile layout. A successful iframe handshake alone is not proof that chart queries succeeded.

Narrow windows select native 12-column, one-chart-per-row dashboard variants; desktop keeps two charts per row. Both layouts reuse the same chart records and row-level selection. Superset calculates canvas dimensions from saved grid columns, so stretching a card with CSS does not resize the actual plot. The live test measures each mobile plotting canvas as well as the card; layout/cadence input selects only server-provisioned dashboard IDs.

## Durable invariants

- A ledger is bound to its repository, target branch and Devin organization. Changing any of these—including repository spelling—is rejected before dispatch. Use a different database for a different execution scope. Exact spelling is intentional because existing durable job keys are case-sensitive.
- On first opening a legacy ledger, available issue, scan and validation keys are checked before binding. Historical keys cannot establish the original Devin organization, and only scan keys establish a branch; verify the existing configuration when upgrading. New ledgers retain the entire scope.
- Dashboard pagination must never drive workflow decisions or lifetime budgets. Operational history is uncapped; aggregate metrics are calculated in Postgres.
- A changed PR invalidates old evidence and queues a replacement in one transaction. Returning to an earlier SHA creates a new validation attempt and preserves the previous session/evidence record.
- Validation fails closed on missing independence, mismatched SHA, missing/duplicate/failing checks or invalid provider attachment metadata. Provider provenance is not proof of artifact contents; humans still review the evidence.
- Blocking webhook intake runs outside the ASGI event loop. Payload size and nested fields are checked before intake.
- Ambiguous provider mutations retain `unknown_effect`. This refactor preserves the receipt-before-readback rule and does not add automatic retries of uncertain writes.

## Repeatable checks

From the repository root, with Python 3.12 and Node 22:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
backend/.venv/bin/ruff check backend
backend/.venv/bin/ruff format --check backend
backend/.venv/bin/pytest --cov --cov-fail-under=80 -q
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run format:check
npm --prefix frontend run build
cd frontend
npx playwright install chromium
npm run test:e2e
```

The browser suite starts its own server at port 8010 with temporary databases, no provider credentials and automation disabled. Screenshots go into ignored `frontend/test-results/`. It tests navigation, review persistence, API failure/recovery, polling overlap, stale responses and cleanup. Set `TEST_PYTHON` if the test interpreter is elsewhere. `E2E_BASE_URL` explicitly opts into testing a different server; the demo interaction test writes demo review/event records there.

The candidate Superset test uses `SUPERSET_E2E=1`; the separate BI analytics test uses `SUPERSET_ANALYTICS_E2E=1` against a provisioned stack. Dashboard tests and mocked providers do not prove a real Devin repair or candidate validation.

`.github/workflows/quality.yml` runs Python lint/format checks, branch-aware coverage with an 80% minimum, TypeScript checks, Prettier, browser tests, a production frontend build and a Docker build. Actions are pinned to verified commit SHAs, permissions are read-only, and no live credentials are supplied. The coverage threshold guards against regression; it is not a claim of complete test coverage.

## Keeping changes maintainable

Add a failing behavioral test for workflow bugs, then change the narrowest responsible service. Keep networking out of evidence policy/report construction and SQL out of routes/services. Keep mutable provider responses at the boundary and expose only the fields each UI page needs. Add a database migration when durable records change. Run local checks before opening a PR; do not rebuild a live worker mid-session to test a refactor.

The runtime uses Postgres with short advisory-lock transactions for single-flight job claims across processes. Real Postgres tests cover concurrency, atomic supersession, receipt persistence, SQL analytics parity, pool saturation and statement-timeout recovery. ASGI tests hold authentication and route I/O open while checking that liveness still responds. Superset owns the embedded charts using a read-only reporting role.

## Scaling boundaries

The deployed AWS topology is a **single-host demo**, not a highly available cluster. It has durable queues, backoff, dead letters and conservative effects handling, but no enabled backups or automatic host failover. The worker's filesystem lock is deliberately local; do not scale it across separate hosts. Generalizing it requires distributed fencing, per-job concurrency limits and isolated execution ownership first.

Scale in measured stages: move Postgres to a managed service and artifacts to object storage; introduce schema migrations as a separately coordinated deployment step; add stateless API replicas within the database budget; then distribute workers with fencing. Keep callback/webhook identities and publication receipts in shared storage. Add SSO/RBAC, external alerting and a restore exercise before broader organizational use. Large history currently loads repository records for some Python analyses; push those scans/aggregations into indexed SQL or precomputed summaries before claiming large-scale analytics capacity. No load-test throughput or availability SLA is claimed.

See [Postgres/Superset](POSTGRES_SUPERSET.md), [recovery design](RESILIENCE.md) and [deployment](AWS_DEPLOYMENT.md).
