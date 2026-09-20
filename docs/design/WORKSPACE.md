# Workspace interface

The workspace keeps four primary destinations: Evidence, Workflows, Analytics and Operations. Nine feature views share a quieter heading, restrained navigation and native expandable controls.

## Interaction choices

- Results appear before configuration. Analysis controls, record filters, candidate selection and secondary tools start collapsed; their summaries retain the active context.
- Execution holds, validation failures, incomplete-data notices and delivery errors remain visible without opening configuration.
- Selecting a run brings its evidence into keyboard focus and view. Closing details returns focus to the original control.
- Operations prioritizes worker status, configured credentials and records needing attention. Configuration, ledger, delivery receipts and repository observations are expandable.
- Filters remain usable on phones, preserve selections across refresh and support reset. Estimated-time assumptions are expandable while the estimate and its limitations remain visible.

## Verification

The production frontend build and 18 frontend tests passed; three separate environment-dependent checks were skipped by the default suite. Two additional tests passed against the local authenticated Docker application: all nine views at desktop and phone widths, and real Superset chart data/filter behavior. Tests also cover keyboard expansion, filter persistence, blocked-record visibility and detail focus restoration.

Deployed revision `aba87b3b9f01cc09f93c400c6a163856e21d519d` to the existing Sydney host. [Code quality CI](https://github.com/Nasdin/superset-auto-engineering/actions/runs/35526277646) passed. Two additional public HTTPS browser tests passed: every feature view at desktop and phone widths, plus all five real Superset charts with cohort filtering, repository isolation and monthly/rolling switching. The container was healthy; unauthenticated analytics and workflow API requests returned 401. See the [verification receipt](../analysis/workspace-interface-verification.json). UI changes do not alter workflow dispatch, provider budgets or approval gates.

## Public screenshots

- Evidence: [desktop](../screenshots/workspace-evidence-desktop.png) · [phone](../screenshots/workspace-evidence-mobile.png)
- Pull Requests: [desktop](../screenshots/workspace-pull-requests-desktop.png) · [phone](../screenshots/workspace-pull-requests-mobile.png)
- Lineage: [desktop](../screenshots/workspace-lineage-desktop.png) · [phone](../screenshots/workspace-lineage-mobile.png)
- Workflows: [desktop](../screenshots/workspace-workflows-desktop.png) · [phone](../screenshots/workspace-workflows-mobile.png)
- Runs: [desktop](../screenshots/workspace-runs-desktop.png) · [phone](../screenshots/workspace-runs-mobile.png)
- Dependencies: [desktop](../screenshots/workspace-dependencies-desktop.png) · [phone](../screenshots/workspace-dependencies-mobile.png)
- Learning: [desktop](../screenshots/workspace-learning-desktop.png) · [phone](../screenshots/workspace-learning-mobile.png)
- Analytics: [desktop](../screenshots/workspace-analytics-desktop.png) · [phone](../screenshots/workspace-analytics-mobile.png)
- Operations: [desktop](../screenshots/workspace-operations-desktop.png) · [phone](../screenshots/workspace-operations-mobile.png)
