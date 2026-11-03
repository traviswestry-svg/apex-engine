# APEX — Canonical Forecast Selection & Directional Snapshot Status Reconciliation

**Source baseline:** `apex-engine-main(20261102-231112).zip` (November 2, 2026)
**APEX release metadata:** unchanged (69.10.47); this is an unpromoted candidate patch.
**Patch scope:** canonical forecast eligibility for future writes; read-only research diagnostics and test coverage.

## Diagnosis

1. `engine/evening_recap.py::_official_forecast_eligibility` previously allowed `NEXT_SESSION_PREP` to take the immutable canonical slot for its target session before market open, even when generated on a prior date.
2. `engine/premarket_directional_features.py::archived_diagnostics` selected only canonical rows and its `archive_diagnostics` returned preparation-mode status before establishing canonical-vs-directional presence. This could obscure a canonical row's status and exclude revision-only session dates.
3. Existing records should not be modified. Some historical canonical rows may have a preparation-origin generated date; these need review, not synthetic replacement.

## Files changed

- `engine/evening_recap.py`: Future official forecasts must be generated on the target calendar date in America/New_York, in `PREMARKET` mode (or existing legacy empty mode), before the regular-session open. `NEXT_SESSION_PREP` is always revision-only.
- `engine/premarket_directional_features.py`: Added canonical-first, read-only lifecycle inventory, including revision-only dates; distinct statuses for canonical without directional snapshot, revision with no canonical, preparation-only, and historical canonical origin requiring review. Directional assessment is taken only from the canonical payload; no revision becomes forecast authority.
- `tests/test_canonical_forecast_selection_reconciliation_candidate.py`: Six tests covering preparation/same-day sequence, immutability, missing canonical, historical preparation-occupied canonical, valid directional payload, and cross-day refusal.

## Research status contract

- `CANONICAL_DIRECTIONAL_SNAPSHOT_NOT_ARCHIVED`: Same-day canonical forecast exists but no `PREMARKET_DIRECTIONAL_FEATURES_V1` payload exists in it.
- `SHADOW_DIRECTIONAL_CONTEXT` / `ABSTAIN_INSUFFICIENT_OR_CONFLICTING_EVIDENCE`: Same-day canonical forecast with archived directional snapshot; no official forecast changes.
- `PREPARATION_OR_NONELIGIBLE_ONLY`: Only noncanonical revisions exist.
- `SAME_DAY_REVISION_WITHOUT_CANONICAL`: Eligible same-day premarket revision exists, but no canonical record exists.
- `CANONICAL_ORIGIN_REQUIRES_REVIEW`: Canonical exists but its recorded mode/date is not a same-day PREMARKET observation (e.g. prior-date preparation). Historical record is left immutable.
- `SNAPSHOT_NOT_ARCHIVED` remains a legacy helper function's generic status, but the persisted read endpoint now provides distinctions.

Each row includes `canonical_presence`, `directional_snapshot_presence`, and `lifecycle` containing canonical timestamps, mode, ID, revision count, and selection audit fields. Source hashes are only reported as present/absent; no historical hash is recomputed or substituted.

## Testing

- 77 focused/integration regression tests passed (combined premarket, canonical, gamma, consolidation and forecast-integrity suites).
- Python compilation passed.
- Full pytest collection **blocked**: `ModuleNotFoundError: No module named 'flask'` in `tests/test_adaptive_confidence_calibration.py` (first collection failure, `--maxfail=1`). Full CI was not completed.
- No real provider integration or deployed production verification conducted.
- No new environment variables or version changes.

## Deployment prerequisites

1. Run **full CI and release-truth checks** in the application environment with dependencies installed, including all gamma-transition regression tests and environment-variable registry governance checks.
2. Deploy only after CI and review, preserving `/data` databases; do **not** patch legacy canonical rows or force them into a different status.
3. Inspect `/api/research/premarket-directional-features?limit=20` and expect distinct canonical/directional classifications for Oct 19, Oct 30, Nov 2, and subsequent new eligible sessions.
4. Verify an eligible same-day PREMARKET brief becomes canonical after a prior `NEXT_SESSION_PREP` revision, and later revisions cannot overwrite the canonical identity.
5. Keep official Evening Recap grading and all decision/execution authorities disabled/unchanged.

**Limitations:** This patch improves future eligibility and the read-model classification. It does not recover missing historical directional snapshots and cannot determine why a historical same-day Morning Brief was not captured unless that event exists in the revisions table.
