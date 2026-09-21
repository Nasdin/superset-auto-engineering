# Isolated local Devin demonstration

This run uses the real Devin and GitHub APIs, driven by the ordinary application worker on the local machine. The worker, database and dashboard run locally; Devin executes its code changes and Superset validation in its hosted session environment. This is separate from the AWS deployment. Do not merge the orchestration feature branch or deploy it without Nasrudin's explicit instruction.

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

The discovery completed and the ordinary worker filed [Superset issue #8](https://github.com/Nasdin/superset/issues/8): SQL Lab drops ClickHouse's per-group `LIMIT BY` when applying its result limit. Devin's reproduction includes actual ClickHouse results showing a group disappearing. This is a discovered existing defect at the pinned release baseline, with an upstream fix identified by Devin; it is not a claim of a previously unknown vulnerability.

Without an operator handoff, the worker started [the separate Devin repair session](https://app.devin.ai/sessions/c1fcd9205f4e448f8320b32c8c57bda5), job `acca8f2d-f2bc-41ad-810b-e37e306ee38b`. GitHub shows the issue author as Nasdin because the application publishes Devin's finding using the configured GitHub token. That author name alone does not mean the issue was manually written.

Devin opened [fix PR #9](https://github.com/Nasdin/superset/pull/9), authored by `app/devin-ai-integration`, against the isolated target. Its head is `c5bf4e29f15d4dc5cd650371c5d60c14b03e591e`. Devin reports 560 passing targeted tests and ten new regressions failing on the baseline. The wider local run has 16 failures that Devin reports also occur at baseline; these are disclosed in its PR description. GitHub CI completed with **44 passing checks, six skipped, and zero failures**. The implementation session did not exercise a live ClickHouse server, so this PR alone is **not** the required independent runtime evidence.

The worker then accepted the implementation handoff, published [its durable issue reply](https://github.com/Nasdin/superset/issues/8#issuecomment-5756824416), and created [draft integration PR #10](https://github.com/Nasdin/superset/pull/10) at `2e52222e6dcd4596972e37472a32915e4697c8b9`. It started [a fresh independent Devin validator](https://app.devin.ai/sessions/894f2b2fba8e40e587165f08661fa1f7), job `e6618c5c-c606-477b-8ed5-82625706b815`, to exercise that exact checkout. No operator resume, handoff rewrite, or manual Superset fix was used. Independent runtime validation and the final review gate remain pending.

The local Learning page records the discovery as a reported observation, a confirmed Knowledge note, and context supplied to the repair session. It does not count that observation as independently validated yet, or claim that memory caused an improvement.

The first independent validator reported successful runtime checks, but its structured report cited different attachment IDs from the real files listed by that session's attachment API. The gate rejected the report and automatically published the failure to [PR #10](https://github.com/Nasdin/superset/pull/10#issuecomment-5756969643), [PR #9](https://github.com/Nasdin/superset/pull/9#issuecomment-5756976512), and [issue #8](https://github.com/Nasdin/superset/issues/8#issuecomment-5756973505). It automatically started [a fresh validator](https://app.devin.ai/sessions/65bef602fa7241f0af60e762e9d93617), job `27a8baaa-eed9-4cb8-a93f-7af703334336`, at the same SHA. This is a real evidence-delivery failure and automatic recovery attempt, not a code regression or a passing release gate.

That live failure exposed an orchestration improvement: a complete report with mismatched attachment references now receives one clarification in its owning Devin session, including the authoritative provider attachment index. Devin must inspect and re-author its references; no filenames are automatically matched and no result is manually rewritten. The original failed gate remains historical. The local worker was restarted with this improvement while the second validator continued; the existing ledger and session were preserved. The full backend suite passed with **417 passed, 30 skipped**; the added cases cover bounds, stale results, restart, uncertain delivery and normal acceptance after a corrected handoff. The end-to-end gate is still pending.

The second validator supplied provider-confirmed artifacts, including a SQL Lab screenshot showing all five expected rows, a saved/reloaded dashboard, browser video, API transcripts, and 586 passing tests with measured coverage. Its gate nevertheless failed because our application incorrectly rejected a successful login request included alongside functional SQL Lab requests. That is an orchestration policy bug, not a demonstrated Superset regression. The failed result and automatic [PR reply](https://github.com/Nasdin/superset/pull/10#issuecomment-5757156879) remain historical; no result was manually promoted.

The ordinary worker started its second and final bounded recollection attempt, [Devin validator `4a8c8b6b01e74611b1aa332e230357a9`](https://app.devin.ai/sessions/4a8c8b6b01e74611b1aa332e230357a9), job `cd3b1f79-087b-431f-a4f7-634d8b433205`, at the same candidate SHA. While that session ran, the local worker was restarted with the corrected policy: at least one functional Superset API request is mandatory; valid login/health setup requests may accompany it; any failed, malformed or unconfirmed request still fails. Artifact ownership also checks the full provider attachment list, independently of the bounded list shown in a corrective prompt. Local regression verification passed with **425 passed, 30 skipped**, including **87 focused evidence/recovery tests**. This latest live gate is still pending.

## What has been verified separately

The simulated-provider lifecycle test drives the real worker and durable store through scan → issue → repair → integration → CI failure → automatic Devin remediation → fresh independent validation → publication → ready-for-review. It restarts the runtime at a handoff and replays observations to check that sessions, PRs, comments and readiness actions are not duplicated. It is explicitly a simulated-provider test, not real Superset proof.

The [feature branch CI](https://github.com/Nasdin/superset-auto-engineering/actions/runs/35574241227) passed at `e9d6825`, including the backend/Postgres, frontend/browser, and container checks. The isolated local dashboard also passed the login, session refresh, logout/revocation, and mobile login browser test.

The earlier orchestration commit `791fa3a` was pushed to main before the user changed the merge/deploy instruction. Its [hosted CI passed](https://github.com/Nasdin/superset-auto-engineering/actions/runs/35568502829). AWS services were not restarted with it. Staged cloud source and build aliases were restored to the preceding revision; the existing hosted worker retained its five-session ledger. Later changes are pushed only to the feature branch.
