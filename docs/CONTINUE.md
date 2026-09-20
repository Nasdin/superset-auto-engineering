# Live workflow continuation checkpoint

Checkpoint: 2026-09-20. The end-to-end goal is active and unfinished. Do not substitute the fixture dashboard or a healthy Superset baseline for a successful autonomous fix.

## Repositories and runtime

- Application: `/Users/nasdin/code/personal/cognition` (the `code` directory resolves to `/Volumes/CORSAIR/code`). Public delivery repository: https://github.com/Nasdin/superset-auto-engineering. Original private remote retained: https://github.com/Nasdin/cognition.
- Superset fork: https://github.com/Nasdin/superset. Clone: `/Users/nasdin/code/personal/superset`.
- Baseline worktree: `/Users/nasdin/code/personal/superset-baseline`, detached at `c37118edd0146019ab0ae4ae1a97a597cb56c88e`, Apache Superset `6.1`.
- Fork target branch: `cognition-release-6.1`. Default branch is unchanged. Issue: https://github.com/Nasdin/superset/issues/1.
- Local control plane: http://127.0.0.1:8000. Actual live job ledger: `/api/live/overview`; automation enabled after take-home API authentication.
- Queued repair job: `15fb900e-d51d-4b0a-8313-bf27f5ba3585`. No session ID, no ACU spent through this application.
- Local baseline Superset: http://127.0.0.1:8188. Compose project `cognition-validation`; app and Celery worker health checks passed.

## Credentials and authorization boundary

GitHub CLI is authenticated as Nasdin. `.env` contains the local GitHub credential, random webhook secret and operator token. `.env.superset` contains synthetic runtime credentials. Both files are ignored and must stay local; never display their values.

Verified signed-in Devin organization: Asmar DE Takehome, `org-f456da0f2e0940808b5c8b3a20312d8c`. The user confirmed token creation. A PAT named Cognition take-home was created September 20, expires September 27, and is stored only in ignored `.env` (mode 0600). Organization session listing returned HTTP 200 with that token. Never display its value.

The installed official Devin CLI reports a personal Devin Pro account. Do not spend personal credits as a fallback; use the configured take-home API organization.

The user explicitly authorized the Nasrudin Slack workspace (`T0C2NTV3Z39`), Tech channel `C0C2NTYCPTR`. The browser is logged in to this workspace. The existing Slack connector only exposes a different workspace; do not use it for this project. Bot-token setup and verified report delivery remain pending.

## Start/rebuild local Superset baseline

The baseline image was already built from the exact worktree:

```sh
docker build --target ci --label cognition.baseline-sha=c37118edd0146019ab0ae4ae1a97a597cb56c88e -t cognition-superset:c37118ed /Users/nasdin/code/personal/superset-baseline
docker compose -f infra/superset.compose.yaml --env-file .env.superset -p cognition-validation up --build -d
docker compose -f infra/superset.compose.yaml --env-file .env.superset -p cognition-validation exec -T superset python < scripts/seed_superset.py
```

On a fresh machine, create `.env.superset` with independent random alphanumeric values for `SUPERSET_SECRET_KEY`, `POSTGRES_PASSWORD`, `MYSQL_ROOT_PASSWORD`, and `VALIDATION_ADMIN_PASSWORD` (at least 32 characters each). The validator username is `validator`. Never commit this file. The environment is isolated and loopback-only, with synthetic rows; HTTP/Talisman is disabled for this local exercise.

Run the optional browser check with `cd frontend && SUPERSET_E2E=1 npx playwright test tests/superset.spec.ts`. The latest run passed: login → SQL Lab → COUNT=3 and SUM=6, with a saved screenshot and video. Review fresh results before later claims. SQL Lab is seeded with Cognition MySQL and `validation.grain_fixture`. The original defect reproduction is in `scripts/reproduce_mysql_grains.py`; its failure output is `evidence/mysql-baseline.json`.

## Remaining acceptance path

1. Take-home token and read-only organization/session access are verified. Do not use the personal CLI account.
2. Rebuild/recreate the application with automation enabled and observe the existing issue's **single** real repair session. Inspect provider status/cost and actual fork PR. Attach every created PR to the Codex task.
3. Let integration form a draft PR from exact component SHAs, followed by a fresh validation session. The validator must start actual Superset from the integrated SHA, run the changed behavior through DB/browser/regression tests, and attach screenshot, video, logs and tests.
4. Inspect the artifact contents and provenance. Observe repaired-candidate report comments on the integration PR, component PR and issue; verify URLs and receipts. The baseline issue report already proves outbox delivery and public artifact access, but does not validate a fix. An agent saying finished is insufficient.
5. Configure the confirmed Slack destination, send the report through the outbox and verify the receipt and visible message. Missing Slack remains an explicit gap.
6. Demonstrate the bounded scheduled scan as a separate real run, a discovered issue and its repair loop if a defect is found. Do not fabricate a discovery. The six-session total cap reserves validation capacity.
7. Recheck the existing temporary tunnel and GitHub webhook before live execution. Real issue delivery and redelivery deduplication are verified in `evidence/github-webhook-live.json`. Port 8001 gateway only, never port 8000.
8. Record actual costs/durations/evidence and durable lessons, final checks and known limitations. Keep the goal active until all requested end-to-end proof is present.

## Failure handling

Unknown session creation blocks further paid dispatch. Reconcile with `python3 scripts/operator.py reconcile --job JOB --session SESSION` only after reading provider tags. For integration writes, POST the authenticated `/api/live/jobs/JOB/resume-integration` endpoint; it performs GitHub readback before writes. Acknowledged reports persist a receipt and retry readback without resending. Unknown publication writes without a receipt must be inspected at the provider before any manual resend. No code auto-merges the release branch.

## Temporary webhook lifecycle

The Cloudflare Quick Tunnel was started with `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8001`; its output is `/tmp/cognition-webhook-tunnel.log`. The active task tool session is `34273`; poll that exact handle or inspect the matching process before restarting. Do not start a duplicate solely because a polling observation times out.

GitHub hook ID: `681964250`. Its current public callback is recorded in `evidence/github-webhook-live.json`. A restarted Quick Tunnel gets a new hostname: update this same hook's URL, retain the local ignored HMAC secret, and verify delivery before claiming it is connected. Never expose port 8000 or 8188. If intentionally shutting down the demo, deactivate this hook before stopping its tunnel. Do not delete unrelated hooks or tunnel processes.

Baseline report: https://github.com/Nasdin/superset/issues/1#issuecomment-5744078328. Evidence branch: `cognition/evidence/baseline-c37118ed`, separate from the release branch. The actual repair job is still queued, zero Devin sessions, and live repair execution is the next step.
