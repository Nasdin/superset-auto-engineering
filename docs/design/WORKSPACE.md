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

Public deployment verification is recorded after release. UI changes do not alter workflow dispatch, provider budgets or approval gates.
