# Live workflow continuation checkpoint

Checkpoint: 2026-09-20. The end-to-end goal is active and unfinished. Do not substitute the fixture dashboard or a healthy Superset baseline for a successful autonomous fix.

## Repositories and runtime

- Application: `/Users/nasdin/code/personal/cognition` (the `code` directory resolves to `/Volumes/CORSAIR/code`). Private remote: https://github.com/Nasdin/cognition.
- Superset fork: https://github.com/Nasdin/superset. Clone: `/Users/nasdin/code/personal/superset`.
- Baseline worktree: `/Users/nasdin/code/personal/superset-baseline`, detached at `c37118edd0146019ab0ae4ae1a97a597cb56c88e`, Apache Superset `6.1`.
- Fork target branch: `cognition-release-6.1`. Default branch is unchanged. Issue: https://github.com/Nasdin/superset/issues/1.
- Local control plane: http://127.0.0.1:8000. Actual live job ledger: `/api/live/overview`; automation disabled.
- Queued repair job: `15fb900e-d51d-4b0a-8313-bf27f5ba3585`. No session ID, no ACU spent through this application.
- Local baseline Superset: http://127.0.0.1:8188. Compose project `cognition-validation`; app and Celery worker health checks passed.

## Credentials and authorization boundary

GitHub CLI is authenticated as Nasdin. `.env` contains the local GitHub credential, random webhook secret and operator token. `.env.superset` contains synthetic runtime credentials. Both files are ignored and must stay local; never display their values.

Verified signed-in Devin organization: Asmar DE Takehome, `org-f456da0f2e0940808b5c8b3a20312d8c`. No existing PAT was present. Browser navigation stopped at the token creation form. The browser tool requires action-time confirmation before creating a new credential; an asynchronous confirmation question was sent and has not been answered. Do not create the token until that answer arrives. The requested token name is Cognition take-home with the shortest available expiry. Store it only in ignored `.env`.

The installed official Devin CLI (`/Users/nasdin/.local/bin/devin`) reports a **personal Devin Pro account**, not the take-home org. Do not spend the personal account's credits as a fallback.

A Slack workspace/channel question is also pending. No Slack notification has been sent. The adapter needs an authorized bot token and a confirmed destination. Do not guess a channel.

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

1. After credential confirmation, configure the take-home org token and verify read-only organization/session access. Do not use the personal CLI account.
2. Rebuild/recreate the application with automation enabled and observe the existing issue's **single** real repair session. Inspect provider status/cost and actual fork PR. Attach every created PR to the Codex task.
3. Let integration form a draft PR from exact component SHAs, followed by a fresh validation session. The validator must start actual Superset from the integrated SHA, run the changed behavior through DB/browser/regression tests, and attach screenshot, video, logs and tests.
4. Inspect the artifact contents and provenance. Observe report comments on the integration PR, component PR and issue; verify URLs and receipts. An agent saying finished is insufficient.
5. Configure the confirmed Slack destination, send the report through the outbox and verify the receipt and visible message. Missing Slack remains an explicit gap.
6. Demonstrate the bounded scheduled scan as a separate real run, a discovered issue and its repair loop if a defect is found. Do not fabricate a discovery. The six-session total cap reserves validation capacity.
7. Activate restricted signed GitHub ingress if required for the live event demo; the local gateway is running and signed/unsigned/duplicate requests are verified, but no public tunnel/webhook exists yet. Port 8001 gateway only, never port 8000.
8. Record actual costs/durations/evidence and durable lessons, final checks and known limitations. Keep the goal active until all requested end-to-end proof is present.

## Failure handling

Unknown session creation blocks further paid dispatch. Reconcile with `python3 scripts/operator.py reconcile --job JOB --session SESSION` only after reading provider tags. For integration writes, POST the authenticated `/api/live/jobs/JOB/resume-integration` endpoint; it performs GitHub readback before writes. Unknown publication delivery must be inspected at the provider before any manual resend. No code auto-merges the release branch.
