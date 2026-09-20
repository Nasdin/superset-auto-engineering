# Superset Auto Engineering · Cognition

A small control plane for autonomous Superset engineering: issue → bounded Devin repair → integration candidate → fresh validator → evidence on GitHub and Slack → human review. Python FastAPI, React/TypeScript/Vite and SQLite, packaged as an API, a durable automation worker and a read-only history importer from one image.

## Run the dashboard

```sh
cp .env.example .env
docker compose up --build -d
```

Open [the dashboard](http://127.0.0.1:8000) or [API docs](http://127.0.0.1:8000/docs). Automation defaults to **disabled**. The shared `cognition-data` volume survives container recreation; `docker compose down` keeps it. The dashboard is deliberately bound to loopback: it has no multi-user authentication.

The repository includes a synthetic SQLite seed at `backend/app/seeds/demo.sqlite3`. Startup loads its dashboard fixtures into the local writable demo database; it never changes the committed seed. The separate live execution database starts empty on a new machine. `.env.example` is committed; `.env`, local databases and credentials are ignored. No credentials are needed to run the explicit example workspace at `/?demo=1`.

The default pages read the real execution ledger: Release validation, Workflows, Devin runs, workflow lineage and Live operations. Empty or unfinished work remains visibly empty or unfinished. Analytics reads imported GitHub PR history in a separate SQLite database; it never fills gaps with fixtures. The old illustrative workspace is available only at `/?demo=1`. The generated design reference is [docs/dashboard-mockup.png](docs/dashboard-mockup.png).

## Current verification boundary

- The dashboard, durable workflow engine, signed GitHub webhook, scheduled scan, provider adapters, integration batching and report outbox are implemented and covered by local tests.
- A real fork issue exists: [MySQL time buckets on Superset 6.1](https://github.com/Nasdin/superset/issues/1). Its reproduction at `c37118edd0146019ab0ae4ae1a97a597cb56c88e` fails 6 of 9 cases against MySQL 8.0; [raw results](evidence/mysql-baseline.json) are retained.
- Superset was built from that exact baseline source. An isolated PostgreSQL/Redis/MySQL/Superset/Celery stack is running locally. A browser test signed in and queried the seeded MySQL fixture, checking three rows totaling six. Screenshot, video and content hashes are recorded in [the baseline manifest](evidence/baseline-manifest.json). This is **baseline qualification, not a repaired candidate**.
- A seven-day Devin token was created on September 20 and verified against Asmar DE Takehome. Live execution is enabled, and Devin opened [repair PR #2](https://github.com/Nasdin/superset/pull/2). Slack reporting is targeted at the authorized Nasrudin workspace, Tech channel. Slack bot reporting is connected and its first message was delivered through the persistent outbox and verified in #tech; [delivery receipt](evidence/slack-live.json). The latest observed independent validator is suspended with `usage_limit_exceeded`; the release gate remains blocked pending a budget decision and completed validation.

The real [baseline evidence report](https://github.com/Nasdin/superset/issues/1#issuecomment-5744078328) was posted through the durable outbox and read back successfully. Its public screenshot/video/reproduction files match the locally recorded bytes. Repeating the publication request left exactly one comment. This qualifies reporting only; the independent release validation is still pending.

## Configure live execution

Use server-side values in ignored `.env`; never put credentials in Vite variables. The intended organization is **Asmar DE Takehome**, with its verified ID in `.env.example`. A personal Devin CLI login is not proof of access to that organization's credits.

Required: `DEVIN_API_KEY`, `GITHUB_TOKEN`, random `OPERATOR_TOKEN`, random `GITHUB_WEBHOOK_SECRET`. Optional reporting requires `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID`. Verify the repository and release branch, then set `AUTOMATION_ENABLED=true` and recreate the containers. Defaults limit each session to 10 ACU, the entire stored run history to 6 sessions, and session duration to 2 hours. The worker reserves capacity for validation and does not reset budgets on restart. A daily scan can be disabled with `SCAN_INTERVAL_SECONDS=0`.

```sh
# Queue an explicitly labeled, authorized fork issue; the worker still needs enabling.
python3 scripts/cognition_operator.py issue --number 1
python3 scripts/cognition_operator.py overview
# Queue one scan for the current schedule window.
python3 scripts/cognition_operator.py scan
```

GitHub issue intake requires the configured author and `cognition:repair` label. Webhooks additionally require the configured repository, actor and valid HMAC signature. The worker polls labeled issues every minute as a fallback and coalesces implemented workstreams after a quiet period. Duplicate issues and deliveries are deduplicated in SQLite.

For public GitHub ingress, start the restricted gateway with `docker compose -f compose.yaml -f compose.webhook.yaml up -d`. Tunnel **only port 8001** and configure the GitHub webhook to `/api/live/webhooks/github` with the same secret and `issues` events. The gateway rejects all other paths. A temporary Cloudflare Quick Tunnel and GitHub issue webhook are now installed and verified. The exact hook and delivery receipts are in `evidence/github-webhook-live.json`; the temporary tunnel requires this machine and its tunnel process to remain running. Never tunnel dashboard port 8000.

## Trust and recovery model

- The repair agent must reproduce the original failure and open a PR in the configured fork. The worker checks the PR's target and head.
- Integration merges exact component commits onto a separate `cognition/integration/...` branch and opens a draft PR. It never merges the release/default branch.
- A **fresh** Devin session validates the full integrated SHA, starts actual Superset, checks services and database results, exercises the browser and runs regression tests.
- Review readiness requires passing mandatory checks, no blocker, distinct provider-confirmed screenshot/video/log/test attachments, and a validator distinct from the implementers. Every later integration PR head change invalidates old evidence. Readiness is agent evidence for human review; it is not automatic approval, merge or deployment.
- GitHub issue/PR reports and optional Slack notifications use a persistent outbox. The UI distinguishes pending, delivered-but-awaiting-readback, sent, failed and uncertain delivery. Acknowledged writes persist a provider receipt before readback; retries confirm that receipt without posting again. GitHub comments must match the queued body and issue, and Slack links come from `chat.getPermalink`. Queued destinations are retained across configuration changes. Provider-confirmed attachment metadata establishes origin; it does not independently prove the content of a video or log. A human still inspects the evidence, and provider URLs may require access or expire.
- A timeout during session creation or external writes becomes `unknown_effect`; it is not blindly retried. Session reconciliation requires the matching job tag. Integration recovery reads the actual branch, merge parents and existing PR before resuming. A lost readback retries using the saved receipt. Unknown writes without a receipt still require operator inspection; no automatic resend follows an uncertain outcome.
- SQLite retains jobs, audit events, delivery IDs, actual reported ACU, publication receipts and the last 20 repository lessons. Lessons are supplied as observations, never trusted instructions.

## Architecture

```text
React dashboard → FastAPI → shared SQLite ledger ← single durable worker
                     ↑                           ↙       ↓        ↘
              signed issue event           GitHub     Devin v3    Slack
                                              ↓
                               exact integration SHA → fresh validator
```

The API and automation worker share the execution ledger. A separate read-only analytics process imports GitHub history hourly into `analytics.db`, so a long historical import cannot delay paid Devin sessions. All three use the same image and Docker volume. Superset's database/cache containers belong to its validation environment. The repository graph shows actual workflow lineage, not a parsed code dependency graph.

## Local development and verification

Python 3.12 and Node 22 are recommended. Start FastAPI and Vite separately:

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

From the repository root:

```sh
backend/.venv/bin/ruff check backend
backend/.venv/bin/ruff format --check backend
backend/.venv/bin/pytest --cov --cov-fail-under=80 -q
npm --prefix frontend run typecheck
npm --prefix frontend run format:check
npm --prefix frontend run build
cd frontend
npx playwright install chromium
npm run test:e2e
```

The default browser suite creates temporary databases and starts an isolated server on port 8010. It needs no running dashboard or provider credentials. See [architecture and code quality](docs/CODE_QUALITY.md) for module responsibilities, regression coverage, CI and migration notes.

The optional Superset browser test requires the isolated runtime described in [docs/CONTINUE.md](docs/CONTINUE.md) and `SUPERSET_E2E=1`. The default browser suite tests this dashboard, not Superset or Devin.

See [the four-day delivery plan](docs/FOUR_DAY_PLAN.md), [continuation checkpoint](docs/CONTINUE.md), and [provider references](docs/providers/README.md).

## Real PR analytics

The `analytics` Compose service reads only the configured fork and `apache/superset`, even when automation is disabled. No Devin credits are consumed. It imports up to 730 days of PR update history, in 100-record pages (maximum 300 pages per repository), then refreshes hourly with a one-day overlap. `GITHUB_TOKEN` raises the API limit; anonymous public reads work but can hit GitHub's rate limit during the initial backfill. Errors and page limits remain visible, with the last successful watermark retained. “Refresh data” reloads the persisted snapshot; it does not trigger a second importer.

The analytics API is `GET /api/analytics/pull-requests`. Filters: repository, completed UTC window end, rolling days (7–180), six calendar months earlier / previous window / custom baseline, author, label, base branch, work signal and tracked repair provenance. A six-month comparison clamps month-end dates and uses equal window lengths. Weekly chart points each summarize the chosen rolling window; overlapping windows are not independent samples.

Time to merge is elapsed calendar hours between `created_at` and `merged_at`. Cohorts are selected by merge date using inclusive dates / half-open UTC timestamps. Closed-unmerged and still-open PRs do not enter duration statistics. The median and nearest-rank P75 show sample sizes; percent change requires covered windows and at least five measured PRs in each. This threshold is a display guard, not a significance test. There is no claim of engineering hours saved or causal Devin improvement. The fork's tracked repair PR numbers come from the complete live ledger and never label an upstream PR with the same number.

Work signals are reproducible title/label heuristics, ordered revert → dependency → fix → other. Current labels and base branches are applied retrospectively. Imported open records are a partial current snapshot, not historical backlog. Follow-up commit counts, review effort, complete issue and commit exploration from the original EDA are not measured by this PR delivery-time view. PR drill-down links and JSON exports (summary, weekly series, selected filters and the displayed 50-row page) make the current analysis inspectable.

For a host-only setup, load your ignored environment and run `python -m app.analytics.sync` from `backend/` alongside FastAPI. No analytics credential reaches the browser. Local history is ignored by Git; clean clones fetch public history rather than inheriting private run records.

A real, public GitHub snapshot is committed at `backend/app/seeds/github-history.sqlite3`: 11,700 upstream PRs and 3 fork PRs fetched September 20, 2026; covered event dates start September 21, 2024. New installations initialize their analytics database from this snapshot and display its actual import time, then the read-only importer updates it. The snapshot contains only allowlisted public PR metadata and import status, with no tokens, PR bodies, private session data or automation jobs. It is never changed at runtime, and existing local history is never overwritten. This makes a fresh clone immediately useful without waiting for a full historical import.

## Product story and Dependabot

The [docs gallery](docs/README.md) contains the editable deck, slide images, repository/commit analysis, and [Dependabot workflow](docs/DEPENDABOT.md). The dashboard now has **Dependabot runs** and **PR evidence** pages. Evidence remains tied to an exact SHA and a fresh validation session; a human merges the PR.
