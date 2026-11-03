# APEX — Directional Evidence Magnitude, Conflict Typology & Shadow Outcome Attribution

Date: 2026-11-03  
Baseline: `apex-engine-main(20261102-231112).zip`, with the latest Canonical Forecast Reconciliation and Premarket Agreement/Abstention Explainability candidates reconciled on top.  
Canonical release: 69.10.47 **unchanged**.  
Scope: read-only shadow research; no execution, scoring, forecast or archive writes.

## Changed files
- `engine/premarket_directional_features.py`: additive `magnitude_conflict_diagnostics()`, `shadow_outcome_attribution()` and fields in existing research endpoint. Does not change `shadow_direction()`.
- `tests/test_premarket_magnitude_conflict_outcome_candidate.py`: frozen-only tests, conflict typology, exact canonical identity, outcome integrity and duplicate handling.

## Inherited compatibility files
- `tests/test_premarket_agreement_explainability_candidate.py`, `tests/test_canonical_forecast_selection_reconciliation_candidate.py` and `engine/evening_recap.py` have been included in prior candidates but **are not modified by this build**. If applying this candidate against the raw November 2 ZIP instead of the reconciled baseline, first apply the prior reconciliation and agreement candidate and verify overlaps. The ZIP here contains only files changed in this build.

## Outputs
- Each eligible canonical direction snapshot gains `details[].magnitude_conflict_diagnostics`: absolute and signed feature magnitude, explicit heterogeneous units, and sign-conflict typology (VWAP recovery / pullback, unanimity, other conflict, incomplete or zero evidence).
- `shadow_outcome_attribution`: read-only exact forecast ID and snapshot hash join to completed evening recaps. Outcomes are measured as **actual session midrange minus frozen forecast center** (not market open-to-close return). Uses existing `extract_observation` quality checks and only canonical same-day premarket origins. Duplicate recaps, missing snapshots, incomplete outcomes, identity mismatches and invalid origins are rejected, never reconstructed.
- No new API routes, environment variables, persistence mechanisms or provider requests.
- Minimum sample count 20 for comparative research flag; no trained model or claimed predictive accuracy. Individual matched historical outcomes may be displayed descriptively with explicit limitations.

## Validation
- Premarket and lifecycle selected tests: 39 passed.
- Gamma integrity, gamma coverage, consolidation governance, forecast provenance, new and related candidate tests: 42 passed.
- Python compile: passed.
- Full repository `pytest --maxfail=1`: **blocked at collection**, `ModuleNotFoundError: No module named 'flask'` in the local environment. Required `requirements.txt` dependencies were not installed. CI and boot smoke remain **not certified**.
- Live provider / production outcome verification: not executed.

## Safe deployment requirements
1. Verify that canonical-selection reconciliation and agreement explainability changes are already installed in the intended base; do not overlay an older version of the same modules.
2. Run the required CI smoke and ratcheted test jobs with `pip install -r requirements.txt pytest`; run full gamma-transition regressions, release-truth and configuration governance checks.
3. Confirm official manifest, application and scheduler version remain aligned and no new env variables are introduced.
4. Deploy only after successful CI and staging. Inspect `/api/research/premarket-directional-features?limit=10` for additional `magnitude_conflict_diagnostics` and `shadow_outcome_attribution`; zero matched outcomes is an acceptable initial result.
5. Do not promote the feature or infer directional probabilities without sufficient chronologically evaluated sessions and independently validated measurement quality.

## Limitations
- SPX/ES feature units differ; no magnitude weighting, statistical standardization or calibrated confidence is claimed.
- The three required ES inputs may be correlated.
- Outcome join is retrospective only, with actual session midrange residual; it is not an intraday open-to-close direction label and cannot prove a profitable trade.
- Historical records missing premarket snapshots are never backfilled.
