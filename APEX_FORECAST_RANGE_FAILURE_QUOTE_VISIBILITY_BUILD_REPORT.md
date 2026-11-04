# APEX — Forecast Range Failure Decomposition & Quote Integrity Research Visibility

**Status:** CANDIDATE / read-only; not production-certified.

## Source and reconciliation

Used `apex-engine-main(20261102-231112).zip` as the base and reconciled the subsequent canonical-selection, premarket availability, agreement explainability, shadow outcome attribution, residual integrity, forecast center construction, and decision-time option quote provenance candidate changes supplied in this conversation. Changed-files-only package contains **one engine module, one test module, and this report**. Prior candidate edits are dependencies and should be retained in the production branch; do not deploy this patch on an older unreconciled branch without merging them.

## Added output fields

* `shadow_outcome_attribution.rows[].forecast_range_failure_decomposition`
* `details[].option_quote_integrity_visibility`
* `shadow_outcome_attribution.rows[].option_quote_integrity_visibility`

### Range decomposition

Uses only `forecast_center_integrity` results with status `VERIFIED`; calculates actual and frozen interval widths, center residual, upper and lower boundary excess, minimum total-width shortfall, required additional half-width **if center stays fixed**, and the feasible interval of centers **if width stays fixed**. If actual interval is wider than frozen width, a feasible fixed-width center interval does not exist. It describes geometry, not causal market drivers, training, or a new predictive multiplier.

Failure types include `CONTAINED`, `PLACEMENT_ONLY_WIDTH_SUFFICIENT`, `WIDTH_INSUFFICIENT_CENTER_ALIGNED`, and `WIDTH_INSUFFICIENT_AND_PLACEMENT_MISMATCH`. Missing, inconsistent, or invalid bounds are `UNVERIFIABLE`.

### Option quote integrity visibility

Copies the previously frozen `forecast_provenance_diagnostics.expected_move.decision_time_source_integrity` verbatim, including call/put identity, bid/ask, original timestamps, quote age, and specific integrity issues. The research endpoint **never recomputes quote age**, rereads providers, or upgrades historical data. Legacy archives lacking the new nested audit report `LEGACY_SOURCE_AUDIT_NOT_ARCHIVED` rather than inventing a result.

Source-specific `SOURCE_VERIFIED`, `DEGRADED_SOURCE_EVIDENCE` and `REJECTED_INTEGRITY` remain the original frozen audit's advisory statuses; no production blocking or recalibration was introduced.

## Verification

* Selected regression tests: **58 passed** including new geometry/quote visibility tests, premarket forecasting, canonical selection, expected-move provenance, gamma coverage, and consolidation guards.
* Python compilation: passed for modified module.
* Full repository `pytest -q`: **blocked during test collection** with 68 import errors, primarily `ModuleNotFoundError: No module named 'flask'`; 1 skipped. Cannot assert full CI passing.
* Canonical release manifest remains **69.10.47**; no new environment variables, tables, migrations, execution permissions, order-routing changes, official forecast mutations, or official grading modifications.

## Deployment gates

1. Merge changed source and tests into the exact current Git commit containing all preceding APEX candidates.
2. Run full CI in the normal requirements environment, including configuration registry, release-truth, gamma-transition, canonical lifecycle and governance tests.
3. Inspect the Nov 4 canonical Morning Brief's nested source integrity. A previous-day quote timestamp must be treated according to its **frozen** audit result; an absent nested audit cannot be promoted to source-verified.
4. Compare the new verified outcome geometry against the reported Oct 30 and Nov 4 bounds; verify zero mutation of forecasts and recap scores.
5. Do not promote any center-displacement scenario or enable paper/live trade execution based on these descriptive samples.
