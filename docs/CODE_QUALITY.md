# Architecture and code quality

The original implementation had useful safety mechanisms (durable jobs, bounded sessions, a receipt-based outbox), but the engine owned intake, integration, evidence policy and rendering. The frontend similarly mixed pages, dialogs and network state. This made changes difficult to isolate and left important failure paths untested.

## Boundaries and patterns

| Boundary | Responsibility | Main files |
| --- | --- | --- |
| Application/runtime factories | Construct dependencies, own one HTTP pool, close it on shutdown or failed startup | `backend/app/main.py`, `automation/runtime.py` |
| Provider port and adapter | Describe the external operations workflows need; implement them with HTTPX; allow fake providers in tests | `automation/ports.py`, `providers.py` |
| Repository | SQLAlchemy/Postgres transactions, durable identity, job claims, metrics and publication receipts | `automation/store.py` |
| Application services | Coordinate issue intake, bounded sessions, integration and validation | `engine.py`, `integration.py`, `validation.py` |
| Evidence policy | Pure acceptance rules for candidate SHA, independent sessions, checks and provider-confirmed artifacts | `evidence.py` |
| Report builder | Convert accepted/failed evidence into escaped, readable Markdown without external calls | `reports.py` |
| Transactional outbox | Store publication intent and receipts; reconcile acknowledged writes without resending | `outbox.py` |
| Frontend pages | Render typed page props; keep shared visuals separate | `frontend/src/pages/`, `components/` |
| Frontend request state | Centralize error handling, abort superseded requests, skip overlapping polls, stop on unmount | `api.ts`, `hooks/usePollingResource.ts` |

Use patterns where they provide a useful boundary. The runtime factory and report builder solve concrete construction and formatting problems. A hierarchy of abstract factories, generic repositories or fluent builders would add ceremony to this small application. Services use composition and structural provider interfaces; tests do not need an inheritance framework.

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

The optional Superset test remains separately gated by `SUPERSET_E2E=1`. Dashboard tests and mocked providers do not prove a real Devin repair or candidate validation.

`.github/workflows/quality.yml` runs Python lint/format checks, branch-aware coverage with an 80% minimum, TypeScript checks, Prettier, browser tests, a production frontend build and a Docker build. Actions are pinned to verified commit SHAs, permissions are read-only, and no live credentials are supplied. The coverage threshold guards against regression; it is not a claim of complete test coverage.

## Keeping changes maintainable

Add a failing behavioral test for workflow bugs, then change the narrowest responsible service. Keep networking out of evidence policy/report construction and SQL out of routes/services. Keep mutable provider responses at the boundary and expose only the fields each UI page needs. Add a database migration when durable records change. Run local checks before opening a PR; do not rebuild a live worker mid-session to test a refactor.

The runtime now uses Postgres with short advisory-lock transactions for single-flight job claims across processes. Real Postgres tests cover concurrency, atomic supersession, receipt persistence and SQL analytics parity. Superset owns the embedded charts using a read-only reporting role. The prepared AWS topology remains a single-host demo; managed availability, user accounts and large-history optimizations remain separate follow-ups. See [Postgres/Superset](POSTGRES_SUPERSET.md) and [deployment](AWS_DEPLOYMENT.md).
