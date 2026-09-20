# Current handoff — 21 September 2026

This replaces the earlier pre-deployment checkpoint. The app is live in Sydney at https://superset-devin.nasrudinsalim.com with Postgres, embedded Superset BI, reviewer login, a signed permanent GitHub webhook and one cloud workflow worker. Local paid dispatch remains disabled. Source: `Nasdin/superset-auto-engineering`, branch `main`; workflow scope: `Nasdin/superset`, branch `cognition-release-6.1`. Secrets remain in ignored `.env` and the root-only cloud configuration.

## Real workflow evidence

- Issue #1 → Devin repair PR #2 → integration PR #4 at `7c5857dc4d2acb3ce324a25681dbd41cedada7da`.
- Independent session `cce0a57c5e0a4fc7ac58df0884d10cbb` built this candidate, ran real MySQL/Superset browser/API checks and uploaded screenshots, video, logs and scoped coverage. Its original immutable handoff schema required a v2 JSON attachment; use the recovery helper to reassess, never fabricate missing fields.
- Scheduled discovery found issue #3, Devin produced PR #5, integration PR #7 awaits independent validation. Dependabot PR #6 has entered actual Devin preparation. Re-read live states before claiming either is complete.
- Review the actual public report receipts in the workspace and GitHub. A failed v1 gate comment remains historical; a corrected v2 report has a new publication key.

## Operator surfaces

Workflows → Schedules & triggers supports saved cadence/pause, Run now, existing issue/PR intake and resuming the same paused provider session. Execution access uses the private operator token, separate from the shared reviewer password. Learning is its own tab and shows knowledge observations, dispatch snapshots and subsequent outcomes.

Workflows and Release gates expose durable recovery state, provider circuits, credit holds, dead letters and publication confirmation separately from validation. Use `docs/RESILIENCE.md` for the recovery procedure. Hosted application limits are 20 sessions total and 20 ACU per new session. Independently, the provider default Message usage limit was raised from $20 to $40, and the existing dependency session cap from $10 to $20. No credits were purchased; other existing session caps are not automatically changed.

The saved discovery schedule supersedes the seed SCAN_INTERVAL_SECONDS after first startup. Changing .env requires container recreation. Do not run a second worker against an independent fresh ledger: it discards capacity and idempotency history.

## Remaining presentation work

Use `CHALLENGE_ACCEPTANCE.md` for the criteria and Loom outline. The required presenter Loom link has not been recorded/submitted. Agent browser MP4 evidence is supporting material, not that deliverable. Do not submit automatically.

## Deployment

Use `docs/LOW_COST_AWS.md`. Cloud source is `/opt/cognition/app`; wrapper `/usr/local/bin/cognition-compose`. Rebuild app/worker serially on the small VM; do not replace the host or databases. No backups/snapshots are enabled per demo preference. Recheck public login, all workspaces, Superset charts, read-only/operator boundaries and anonymous evidence rendering after each deployment.
