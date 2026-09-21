# Human feedback and Devin memory

Open **Workflows → Learning → Human feedback**. The page follows each correction from the person and reason behind it through native Knowledge storage, the exact revision supplied to later work, and the later validation outcome. Run observations remain in a separate journal.

## Give or edit feedback

1. Expand **Execution access** and enter your private `OPERATOR_TOKEN`. The shared reviewer password alone cannot change memories.
2. Choose **Give feedback**, select the source run, and enter your name, a short title, why the result was wrong, and the guidance Devin should remember. Alternatively, inspect a run observation and choose **Correct this learning** to override that observation.
3. Save. The application commits an immutable revision and audit event to Postgres or SQLite. Native Knowledge storage stays pending until the worker confirms the provider receipt.
4. Select **Edit memory** to replace the guidance or retire it. The original author, subsequent editors, reasons and full revision history remain visible. A concurrent edit returns a conflict rather than silently overwriting someone else's correction.

Names are **operator reported**, not individually authenticated identities: this demo uses a shared reviewer login and a separate operator token. Deployments needing verified authors should attach SSO identity to the command server-side. Do not put secrets into feedback; active guidance is sent to Devin for this repository.

## How it carries forward

The ordinary worker synchronizes active revisions to Devin Knowledge when `LEARNING_ENABLED=true` and the service account has `ManageOrgKnowledge`. It confirms note scope, content and enabled state by reading the note back. Superseded notes are disabled before replacements or new session dispatch. Unknown creation outcomes are reconciled by their stable content marker instead of blindly creating another note.

Current corrections take priority in the bounded context of ten observations. The database records the exact lesson revision and confirmed native note identifier supplied with a paid session. A database lease serializes feedback edits, Knowledge synchronization and context-to-session creation. A definitely unsent context can be rebuilt after feedback changes, with its old snapshot retained. Confirmed sessions keep their historical context; editing a memory does not retroactively change a running session.

Memory is guidance, never permission to weaken tests, bypass a release gate, merge or deploy. The page separates **recorded**, **remembered**, **supplied**, **agent-reported application**, and **independent validation**. The application indicator requires the agent's final summary to name the exact feedback revision. Supply alone is not consumption or proof of improvement.

The outcome chart uses recorded monthly validation results and displays cohort sizes. It does not attribute changes to memory or invent a trend when history is insufficient. A controlled evaluation across comparable tasks would be needed for a causal improvement claim.

## Real local example — 21 September 2026

The [first PR #6 validator](https://app.devin.ai/sessions/ae91060b80834cab9dc403fc6e2cd863) reported 196 passed tests and one failed test, while describing regression as passed because the failure reproduced on the baseline. The gate rejected that contradiction.

Nasrudin Salim, with Codex as the disclosed operator, recorded **“A failing regression must never be reported as passed.”** The guidance requires preserving actual commands/counts/logs, repairing on the same PR branch, and obtaining fresh independent evidence before review readiness. A second revision explicitly distinguishes baseline diagnosis from acceptance and asks later runs to name the applied revision.

| Record | Confirmed identifier |
| --- | --- |
| Source validation job | `e2b7a06e-77a2-4323-93a9-14721ac7fa67` |
| Original feedback revision | `6f0d0993-49d8-447a-9983-970fb5488d6e` |
| Retired native note | `note-f8b21e1b4bf140e8a81cf37772c06ea6` — read back disabled |
| Current feedback revision | `9e7e9c99-616d-4b68-bf90-819b6803e6d4` |
| Current native note | `note-62aafc5847f04944a2757c2f11837210` — exact content read back enabled |
| Later validation job | `9a18ed2a-a491-40e4-b1c4-8fe46e446b5c` |
| Later independent Devin session | [4353fe8925e741c4a0e1357082abb7af](https://app.devin.ai/sessions/4353fe8925e741c4a0e1357082abb7af) |
| Candidate being checked | `9cbf3d7f54ed803674fa8a671fc3ff341bdc8ce5` |

Both revisions were recorded through the authenticated application API; the ordinary worker synchronized them. The later session's frozen context contains the current revision. At this checkpoint its validation is running: explicit application and successful acceptance remain unproven. The earlier repair started before this feedback and is not attributed to it.

Browser tests exercise save, edit, retire, history, author attribution and the mobile layout. Backend tests cover idempotence, stale edits, overridden observations, disabled native notes, uncertain provider effects, immutable dispatched context and lease races. A real Postgres concurrency test verifies that simultaneous edits have exactly one winner.
