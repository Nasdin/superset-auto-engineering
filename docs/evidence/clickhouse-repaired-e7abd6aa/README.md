# Fresh evidence after autonomous CI repair

This is real Devin evidence for **`e7abd6aa25a60f108f8b34fde2e0aa323821f171`**, the repaired head of [Superset PR #10](https://github.com/Nasdin/superset/pull/10). The independent [validator session](https://app.devin.ai/sessions/5eb6e99b69e340c8aee15f2cf60e57f0) started after a separate Devin session repaired the Cypress binary installation failure. No Superset fix or successful validation result was supplied by Codex.

[Published exact-revision evidence report](https://github.com/Nasdin/superset/pull/10#issuecomment-5758174623).

The gate accepted fresh services/database/browser/API/regression/coverage checks: **586 tests passed, zero failed/skipped**; scoped coverage **531/613 lines** and **133/164 branches** across the parser and ClickHouse integration. The recorded CI snapshot contains 57 reported checks/contexts, all successful or skipped. SQL Lab preserved all five expected fixture rows including the third group; the saved dashboard retained them after reload. This does not claim every Superset path or repository-wide coverage.

The application automatically asked this validator once to correct mismatched attachment references using its own provider-confirmed attachment index. Devin corrected the structured output without changing measurements or re-uploading files. The application then verified ownership and archived the evidence. No URLs were manually substituted to promote the gate.

Selected files here are byte-for-byte copies of the accepted archive, including the 42.5-second H.264 browser recording, two screenshots, API transcript, test report and coverage JSON. `readback.json` records source/public URLs, hashes, HTTP readback and publication receipts for all 22 artifacts. All public URLs returned HTTP 200; the SQL Lab image also loaded at 1600×1200 through GitHub's image proxy.

The PR remains open and unmerged. Human review is still required. AWS has not been deployed. Original public-media URLs use a temporary local tunnel; committed copies remain available after that tunnel stops. Earlier evidence under `../clickhouse-local-validation` belongs to the previous SHA and is historical.
