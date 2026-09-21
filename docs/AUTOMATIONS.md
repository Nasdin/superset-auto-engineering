# Automation catalogue

Open **Workflows → Automations**. These recipes are managed by this application through the Devin API. They are not copies synchronized with the native Devin Automations settings. Each recipe has a durable schedule, manual Run now, configuration state and a filtered run history. Operator access is required to change schedules or start paid work; the reviewer password only grants viewing access.

| Recipe | Default cadence | Output |
| --- | --- | --- |
| Autonomous correctness discovery | Daily, seeded by `SCAN_INTERVAL_SECONDS` | One reproducible finding → fork issue → repair → independent validation |
| Dependency Vulnerability Scanner | Daily, initially paused | One verified dependency finding → issue → repair → independent validation |
| Secret Scanner | Daily, initially paused | At most one scoped fix PR replacing a hardcoded credential with environment configuration → independent validation |
| Code Pattern Enforcer | Weekly, initially paused | Fork conventions from AGENTS/CONTRIBUTING, lint configuration and maintained modules → one reproducible finding → issue → repair → independent validation |
| OWASP Security Hardening | Weekly, initially paused | One reproduced application-security finding → issue → repair → independent validation |
| Bug Report Triage | Daily, initially paused | Evidence-backed review of existing reports; report only. Labelled issues use the existing repair event intake |
| Release Readiness Review | Weekly, initially paused | Review of existing PRs/checks/blockers; report only, never approval or deployment |
| Cloudflare Security Audit | Weekly, initially paused | Redacted read-only review of account audit activity; report only |

Existing discovery settings are preserved. Enabling a recipe schedules its first tick one full interval in the future. **Run now** queues one immediate intent without enabling its schedule. Pausing prevents future ticks; already queued jobs and running sessions remain. Global `AUTOMATION_ENABLED`, session capacity, ACU bounds, provider circuit breakers and unresolved holds still apply.

## Failure and duplicate protection

Schedules and job provenance live in Postgres (or SQLite locally). Edits require the last observed schedule version, so stale browser tabs cannot overwrite newer edits. Concurrent retries of the same manual request return the same job. Missed schedule ticks coalesce into one job, and an active or held run prevents another run of that recipe. Every recipe gets checked even if another fails; scheduler failures appear on its card and degrade worker health.

A Secret Scanner PR owns its recipe while open. Before considering another run, the scheduler reads its current GitHub state. Failed readback does not release ownership. Once the PR closes, the scheduled scanner skips the already scanned baseline until the release branch changes. A manual run can explicitly recheck a completed baseline. Maintenance PRs also own their repair and validation intake, avoiding a second paid repair session when labels/events arrive.

Scans require a final structured result and a baseline reproduction for a finding. Missing output is not an empty successful scan. Source/scanner failures become visible holds. Secret scans never test exposed credentials, rotate/revoke access, or print secret values. Rotation remains an operator action. A clean scan records the actual checks; a fix must point to the configured fork, job-owned branch and exact SHA.

A prepared maintenance result, its GitHub publication intent and fresh validation child are committed together through the transactional outbox. No claim of passing evidence is made by the implementation agent. The independent validator must start the candidate's Superset runtime and supply accepted screenshots, API transcripts, tests, coverage and logs before the release gate can pass. Existing provider reconciliation, bounded retries and dead-letter handling apply; see [resilience](RESILIENCE.md) and [PR validation](PR_VALIDATION.md).

## Cloudflare prerequisite

Create a dedicated Cloudflare credential with **Account Audit Logs: Read**, scoped only to the intended account. Store that credential as a secret in the intended Devin organization; put its secret ID (not the token) in `CLOUDFLARE_AUDIT_SECRET_ID` and the account ID in `CLOUDFLARE_ACCOUNT_ID`. Recreate the app and worker after changing `.env`.

The recipe is unavailable until both settings exist. Configuration presence alone does not verify provider permissions; a real run reports unavailable access as a blocker. The session receives only the selected secret ID, requests the last seven days of logs, and must omit raw log bodies, credentials, emails and IP addresses from reports. It cannot change DNS, security policies or account settings. These credentials are not supplied to the other recipes.

## Understanding limits

`DEVIN_MAX_ACU` bounds each new API-created session. `DEVIN_MAX_SESSIONS` bounds the deployment ledger. Devin's per-message dollar cap and organization credits are separate provider controls. Raising a cap does not replenish credits or necessarily resume a session.

A provider `usage_limit_exceeded` or `total_session_limit_exceeded` is a **session hold**, not proof that the organization ran out of credits. The application keeps that job visible without opening an organization-wide credit breaker. Actual organization-credit errors still stop new paid dispatch. Inspect the linked session, adjust its cap deliberately if appropriate, then use the same session's resume control only if work remains. Unknown delivery of a resume request is held for reconciliation, never blindly resent. New catalogue recipes do not automatically raise limits.

## Run attribution and evidence

Each original job carries its recipe ID and trigger source; created Devin sessions include `cognition-automation:<id>` and the job correlation tag. Repairs, integrations and validation jobs inherit provenance through parent/member relationships. A combined integration can belong to multiple automations. The catalogue filter and job details show those origins alongside the Devin link and actual state. Counts include all related ledger jobs; the history list displays the latest 100. Enabled schedules, queued jobs and review reports are not evidence that a fix passed validation.
