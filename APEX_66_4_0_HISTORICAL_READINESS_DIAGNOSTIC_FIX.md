# APEX 66.4.0 — Historical Readiness Diagnostic / Repair

## Objective
Repair the Historical Readiness pipeline so unassessed observations are not falsely reported as quality exclusions, and make every observation's blocking stage visible.

## Changes
- Historical Readiness schema upgraded to `apex.history.readiness.v2` / build `66.4.0`.
- `Excluded` now means **assessed and quality-ineligible** only.
- New `Unassessed` count separates records that have never run through the data-quality gate.
- Exclusion-rate denominator is now assessed observations only. Unassessed rows no longer create a false 100% exclusion rate or false `DEGRADED_HISTORY` state.
- Added per-recommendation diagnostic states:
  - `MISSING_EVIDENCE`
  - `UNASSESSED`
  - `QUALITY_EXCLUDED`
  - `AWAITING_REAL_OUTCOME`
  - `LEARNING_ELIGIBLE`
- Added `GET /api/historical-readiness/diagnostic`.
- Added `POST /api/historical-readiness/reconcile`.
- Reconcile idempotently:
  1. captures missing evidence packages from persisted recommendation-ledger records;
  2. runs missing quality assessments;
  3. bridges only explicit persisted terminal ledger outcomes into governed graded outcomes.
- Reconcile never infers a WIN/LOSS, never calls a broker, and never calls a market-data provider.
- Historical Readiness dashboard now shows Missing Evidence, Unassessed, Excluded, Graded, Pending Outcome, pipeline blockers, and a row-level diagnostic table.
- Added `Repair / Reconcile` control to perform a safe catch-up pass after deploy/restart.

## Expected behavior after deploy
Open **Operations → Historical Readiness** and press **Repair / Reconcile** once. The page will show exactly where the current 17 observations are blocked. If they were merely unassessed/missing evidence, they will be repaired. If they have genuine quality defects, they will remain excluded with the exact defect codes. If they are quality-eligible but do not yet have a real terminal outcome, they will show `AWAITING_REAL_OUTCOME` rather than being mislabeled as excluded.

## Validation
- Python compilation passes for modified engine/routes.
- Historical Readiness non-Flask unit tests: 5 passed.
- Full Flask route tests could not run in this build container because Flask is not installed in the local execution environment; route module compilation passed.
