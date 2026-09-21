# Isolated local Devin demonstration

This run uses the real Devin and GitHub APIs, driven by the ordinary application worker on the local machine. It is separate from the AWS deployment. Do not merge the orchestration feature branch or deploy it without Nasrudin's explicit instruction.

- Orchestration branch: `feat/devin-autonomous-verification` in `Nasdin/superset-auto-engineering`.
- Superset target branch: `cognition-local-e2e-20260921` in `Nasdin/superset`, copied without code changes from release baseline `c37118edd0146019ab0ae4ae1a97a597cb56c88e`.
- Intake label: `cognition:local-e2e-20260921`. The AWS worker uses a different target branch and label.
- Storage: local Postgres database `cognition_local_e2e_20260921`; isolated artifact directory and worker lock.
- Bounds: at most eight local sessions, 20 ACU per new session, two automatic recovery attempts. This is a separate, explicitly authorized test budget; it does not reset the hosted ledger or imply the account has unlimited credits.
- No recurring local discovery schedule; one explicit manual discovery event starts this chain. Further steps come from worker handoffs and repository observations.
- The local dashboard runs on loopback only. A temporary Cloudflare Quick Tunnel exposes a separate server with only `/public-evidence/<content-hash>`; private APIs, execution controls and the database are not exposed. These test URLs last only while that local tunnel runs.
- Secrets stay in ignored `.env.local-e2e`; local process state stays in ignored `data/local-e2e/`. None belongs in Git.

## Execution record

Initial discovery job: `6385ea8a-47ae-402a-842f-feceff319d8b`.

[Real Devin discovery session](https://app.devin.ai/sessions/3def8e1dff9f43b4853d4b2fdd7e972e) began on 21 September 2026. It was instructed to reproduce a real, distinct defect and check existing issues/PRs before reporting. **The live end-to-end outcome is still pending.** A test passing locally is not evidence that this Devin session repaired or validated Superset.

## What has been verified separately

The simulated-provider lifecycle test drives the real worker and durable store through scan → issue → repair → integration → CI failure → automatic Devin remediation → fresh independent validation → publication → ready-for-review. It restarts the runtime at a handoff and replays observations to check that sessions, PRs, comments and readiness actions are not duplicated. It is explicitly a simulated-provider test, not real Superset proof.

The earlier orchestration commit `791fa3a` was pushed to main before the user changed the merge/deploy instruction. Its [hosted CI passed](https://github.com/Nasdin/superset-auto-engineering/actions/runs/35568502829). AWS services were not restarted with it. Staged cloud source and build aliases were restored to the preceding revision; the existing hosted worker retained its five-session ledger. Later changes are pushed only to the feature branch.
