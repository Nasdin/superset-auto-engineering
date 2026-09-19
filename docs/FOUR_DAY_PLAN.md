# Four days to one credible end-to-end demo

## Day 1 — Evidence-first product shell

This repository provides the React dashboard, FastAPI contract, local ledger, Docker packaging, fixtures and tests. Choose one reproducible, bounded Superset issue on a fork. Write explicit behavior-based acceptance criteria and retain a failing reproduction. The five workstreams in the UI are illustrative; the first real demo should use one or two issues.

## Day 2 — Event → Devin → pull request

Implement a signed GitHub webhook for labeled issues in the chosen fork. Persist delivery ID before scheduling; constrain repo and event type. A single durable worker claims jobs transactionally and dispatches a Devin session with bounded scope, budget and acceptance criteria. Record provider session ID and poll status. A timeout on session creation is `unknown_effect`: reconcile before retrying to avoid duplicate paid sessions. Expose actual session and PR links in the UI.

Current official Devin documentation uses organization API v3: `https://api.devin.ai/v3/organizations/{org_id}/sessions`. Confirm the demo organization's credentials and create/get-session schemas before implementation; do not assume legacy API key compatibility.

Acceptance: create one issue in the fork, observe one durable job and one real Devin session, inspect a real remediation PR. Duplicate webhook delivery must not dispatch again.

## Day 3 — Integrated candidate → independent validation

Pin an integration candidate to a full commit SHA, retaining the component PR SHAs. Batch changes with a short quiet period and maximum wait; allow one validation per repository, with a newest-pending candidate slot. A newer SHA invalidates eligibility of older evidence.

Use a fresh validator session, distinct from implementation. Boot the pinned Superset environment, verify services and DB, execute regression tests, and interact with the browser. Capture evidence for the specific changed behavior, including failures. Each artifact needs candidate SHA, validator ID, command/journey, timestamp, exit status and content hash. Capture the environment image/config identity. Store files locally for the demo and metadata in SQLite. Never equate a session marked complete with successful validation.

Acceptance: show a real browser capture, DB check, service log and regression result for one exact SHA. Deliberately fail a required check and demonstrate that the gate blocks. A repaired revision needs a new independent validation.

## Day 4 — Human review and a defensible pitch

Implement a review gate that requires all mandatory checks, complete provenance, independent validation and a current candidate. Keep approval distinct from merge. Recheck the PR head/base before any later merge operation. Add authenticated reviewer attribution before remote exposure.

Rehearse a short story: failing user behavior → issue event → autonomous fix → integrated revision → independent proof → human decision. Measure observed duration, actual cost, attempts and reviewer actions. Do not claim hours saved without a measured baseline. Show duplicate events, stale SHA, failed checks and unknown provider outcomes in the technical walkthrough.

Final deliverables: reproducible Docker startup, setup documentation, real PR/session links, evidence manifest, screenshots/video, known limitations and a short VP-oriented demo. Preserve fixture mode for offline rehearsals and label it conspicuously.

## Scope cuts

No general-purpose multi-agent platform, self-improving memory, automatic production deploy, graph database or inferred productivity savings. The graph can stay a simple candidate/workflow relationship view. The strongest proof is one complete real remediation loop, not five simulated ones.

## Sources checked during setup

- [Devin API overview](https://docs.devin.ai/api-reference/overview)
- [FastAPI container deployment](https://fastapi.tiangolo.com/deployment/docker/)
- [Vite guide](https://vite.dev/guide/)
