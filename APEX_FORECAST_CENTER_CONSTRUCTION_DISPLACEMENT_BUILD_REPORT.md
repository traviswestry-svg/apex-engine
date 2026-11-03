# APEX — Forecast Center Construction Provenance & Directional Displacement Research

**Baseline:** `apex-engine-main(20261102-231112).zip`, overlaid with the successive changed-file candidates for canonical forecast reconciliation, agreement explainability, magnitude/conflict outcome attribution, and center residual integrity. Those successive candidate overlays were used because the November 2 repository predates them; confirm this composition against the actual latest production Git SHA before cherry-picking.

**Release:** `69.10.47` unchanged. **Authority:** read-only shadow research. No official forecast, grading, storage schema, execution, or broker changes.

## Changed files

- `engine/premarket_directional_features.py`
- `tests/test_forecast_center_construction_provenance_candidate.py`

## Implementation

- `forecast_center_construction_provenance()` reads the **stored** Morning Brief deterministic expected-move inputs and `forecast_provenance_diagnostics.expected_move`. Checks that the frozen SPX range equals `reference_spot ± selected_one_sigma`, checks consistency of the archived deterministic provenance, and verifies the `STRADDLE_FIRST` versus `IV_FALLBACK` selection path. Reports `ARITHMETIC_VERIFIED_SOURCE_UNVERIFIED`, `INCONSISTENT`, or `UNVERIFIABLE`.
- Raw option quote timestamp, expiry, bid/ask, and calculation time-to-close are not reliably archived in this existing path. They remain explicitly unverified rather than being derived from outcomes.
- `shadow_directional_center_sensitivity()` uses only verified frozen premarket ES return, frozen SPX reference spot, and selected one-sigma. It reports **two predeclared, untrained research sensitivities** (half and full overnight ES percentage displacement mapped to SPX points), each capped at one frozen sigma, preserving the original range width. This is an illustrative cross-instrument proxy, **not a validated recommendation or executable forecast**.
- If an exact matched and integrity-verified completed recap exists, the same counterfactuals are retrospectively scored against its actual high and low. Outcome values never feed offset construction, and no parameter is selected using the outcome.
- The existing `archive_diagnostics` and `shadow_outcome_attribution` paths are extended additively; historical records are not rewritten. Missing and inconsistent frozen inputs fail closed.

## Validation

- Selected premarket, canonical, gamma-integrity, and consolidation regression tests: **65 passed**.
- Python syntax compilation: **passed**.
- Full repository CI with `pytest -q -x`: **blocked during collection** at `tests/test_adaptive_confidence_calibration.py`, because `flask` is missing (`ModuleNotFoundError`). No release certification claimed.
- Release manifest remains `69.10.47`; no environment variables added, no new runtime modules, and no route additions.
- Production validation: **not performed**.

## Research cautions

- The existing October 30 observed forecast center error is arithmetically verified, but the raw SPX option quote/source timing is not fully proven.
- ES and SPX need not share identical return timing or level; converting ES overnight percentage to SPX center offset can be misleading.
- One eligible completed directional session in the submitted diagnostic is far too few to compare alternative center construction reliably; the existing `comparison_ready` minimum remains 20 and no calibration or performance claim is made.
- Only exact canonical morning/recap matches are eligible for retrospective scoring; legacy or preparation-occupied canonical records remain excluded.

## Deployment requirements

1. Reconcile this patch with the current production Git commit and the previously staged candidate overlays; do not overwrite newer changes.
2. Install declared runtime dependencies and pass full repository CI, version/release governance, and gamma transition regressions.
3. In staging, check `details[].forecast_center_construction_provenance`, `details[].shadow_directional_center_sensitivity` and matched `shadow_outcome_attribution.rows[]` for new sessions.
4. Verify that historical canonical IDs, snapshots, official forecast selection and scoring, and execution authority remain unchanged.
