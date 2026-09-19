# Cognition · Release assurance

An evidence-first dashboard for autonomous Superset engineering. Python FastAPI, React/TypeScript/Vite, SQLite, one Docker container. Local Git repository; no remote is configured.

## Run

```sh
docker compose up --build -d
```

Open http://localhost:8000. API docs: http://localhost:8000/docs.
Data survives container recreation in the `cognition-data` Docker volume. Stop with `docker compose down` (keep the volume). Port binding is localhost only: this prototype has no authentication and must not be exposed publicly.

### Local development

Python 3.12 and Node 22 recommended. In two terminals:

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to FastAPI.

## What works today

- Responsive release dashboard: exact candidate SHA, validation checklist, pipeline and evidence gallery.
- Workflows with search and a local issue-event simulator; duplicate delivery IDs are deduplicated atomically.
- Devin run trace viewers, an interactive illustrative repository graph, and fixture analytics.
- Evidence viewer for screenshots, logs and tests, JSON export, and explicit unavailable-API handling.
- SQLite-backed demo review decisions; stale candidate SHA returns 409. Real release approval is always blocked.
- A polished generated mockup at `docs/dashboard-mockup.png` and actual UI screenshots in `evidence/` after browser checks.

## Honest demo boundary

The Superset issues, session IDs, candidate commit, durations, statuses, chart preview, graph relationships and evidence are **fixtures**. They are not upstream findings or actual Devin/Superset runs. The chart is an illustrative UI preview, not a captured Superset screenshot. Exported JSON includes `mode: demo`. Decisions only record local intent; they never approve, merge or deploy. The pending independent review check remains pending because no real independent validation happened, even after a demo decision is recorded.

No GitHub webhook, Superset checkout, Devin API dispatch, polling worker, real artifact ingestion or production authentication is connected yet. The current simulator stores events but does not execute them. Review decisions are append-only; separate submissions create separate ledger entries. Do not automatically retry a decision after an uncertain response—inspect the activity ledger first.

## Architecture

```text
Browser / React + Vite
          │ /api
          ▼
FastAPI ───── SQLite event + review ledger
   │
   └── Built frontend files (same origin, same container)
```

Keep one API and one database for this four-day exercise. Add a small durable worker and Devin adapter in the same repository; no Redis, distributed orchestration platform or graph database is needed for the first complete demonstration. See `docs/FOUR_DAY_PLAN.md` for the live path and acceptance gates.

## Verification

```sh
cd backend
.venv/bin/python -m pytest -q
cd ../frontend
npm run build
npx playwright install chromium
# With Docker app running; omit E2E_BASE_URL to use Vite on port 5173
E2E_BASE_URL=http://127.0.0.1:8000 npm run test:e2e
```

Browser checks cover evidence inspection, demo review persistence, workflow search, event creation, page navigation, narrow-screen overflow and API outage handling. They exercise this application, not Superset. Backend checks cover durable decisions, stale SHA, concurrent event deduplication and the real-approval block.

## API

| Endpoint | Behavior |
| --- | --- |
| `GET /api/health` | SQLite health, demo mode |
| `GET /api/dashboard` | Fixtures plus local activity |
| `POST /api/demo/events` | Save `{delivery_id, title}`; deduplicate by ID |
| `POST /api/demo/decisions` | Save `{sha, decision, note}`; check SHA |
| `POST /api/releases/approve` | Always 409: demo evidence is ineligible |

Do not add API keys to frontend code. Future Devin credentials belong only in the backend environment. The current scaffold needs no credentials and makes no paid API calls.
