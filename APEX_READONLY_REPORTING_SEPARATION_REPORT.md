# APEX Trigger Observatory — Read-Only Reporting & Historical Reconciliation Separation

## Baseline
November 12, 2026, updated repository `apex-engine-main(20261112-221036).zip`; canonical release `69.10.47`. This is an incremental candidate and **is not deployed**. Stage 3 storage work is deferred.

## Source findings
- `initialize_store()` performs CREATE/ALTER/INDEX initialization and defaults to `_reconcile_window_integrity_conn`, which scans historical triggers and writes derived trigger and observation fields.
- Reporting endpoints `predictive_validation`, `effectiveness`, `history`, and `trade_visualization` previously called `initialize_store()` as a side effect; delegated predictive/observation/regret views inherit the path.
- `outcome_grader.horizon_integrity()` previously used `evidence_pipeline._connect`, which can initialize or migrate the evidence ledger despite only reading canonical grade horizons.

## Corrections
1. Remove `initialize_store()` calls from those four reporting entrypoints. They now use their existing `read_only=True` database connections and will not reconcile or migrate schemas just to serve a report.
2. Provide `reconcile_historical_observation_windows(path=...)` as an **explicit write-side maintenance entrypoint**. It delegates to the existing validated `initialize_store(..., reconcile=True)` so no reconciliation algorithm or field semantics are changed. Existing writer initialization paths and `sync_canonical_outcomes` are untouched.
3. Read canonical outcome horizon-integrity records through `canonical_connection(..., read_only=True)` rather than the evidence ledger's write-capable `_connect()`.
4. Add regression tests proving the reporting paths leave stale legacy rows and raw observations unchanged, while explicit maintenance still reconciles them; no trigger DB is created for a missing store.

## Compatibility and boundary
- No schema change, new environment variable, trading authority, scan scheduling, broker routing, settlement eligibility, fuzzy canonical identity matching, or synthetic evidence.
- Previously, viewing a report could reconcile persisted legacy history. After this change, reports compute eligible derived window metrics in memory where supported but will no longer persist those repairs. Legacy persisted columns consumed directly by `history` or `trade_visualization` may remain stale **until an explicit, approved maintenance reconciliation** runs. This is an intentional side-effect separation, not an assertion that every legacy report value is identical without reconciliation.
- Do not schedule the explicit maintenance entrypoint automatically on read requests. An operator-approved maintenance invocation can run on the existing, backed-up database with normal SQLite writer locking and audit procedures.
- Predictive validation continues to materialize all matching trigger rows; bounding historical query memory is a separate future optimization and not part of this patch.

## Local validation
- Selected targeted, gamma transition, release-truth, consolidation and settlement suite: **95 passed** (`selected_tests.log`).
- Two new reporting/maintenance isolation tests included in the 95.
- Python compilation of edited modules succeeded.
- Full suite attempted and failed at collection, `ModuleNotFoundError: No module named 'flask'` (`full_ci_attempt.log`); therefore **not fully CI-certified**. Also run the repository's smoke-route test in the configured CI environment and confirm GitHub required checks before deployment.

## Deployment checklist
1. Diff `APEX_READONLY_REPORTING_SEPARATION.patch` against the production branch; reject any conflict rather than overwrite later files.
2. Run required full CI with installed runtime dependencies and route-import smoke test.
3. Confirm `predictive_validation`, `effectiveness`, `history`, `trade_visualization`, and `outcome_grader.horizon_integrity` remain read-only under SQLite trace/authorizer tests.
4. Exercise known historical and current trigger cohorts; compare report values where raw persisted columns may have previously relied on implicit reconciliation.
5. If legacy repair is needed, take a backup and invoke the explicit maintenance function separately with logging, then verify exact trigger identity/window invariants.
6. Continue Stage 2 production-memory monitoring; Stage 3 remains on hold.
