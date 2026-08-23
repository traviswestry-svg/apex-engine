# APEX 68.9.0 — Microstructure Calibration & Decision-Evidence Promotion Governance

## Purpose
68.9 closes the gap between collecting real ES L2/MBO observations and allowing microstructure to become reviewable APEX decision evidence. It adds outcome labeling, feed-integrity measurement, offline calibration, a shadow confirmation score, and explicit promotion-readiness gates. It does **not** activate microstructure in production decisions.

## Added
- Explicit microstructure outcome ledger keyed to persisted observation IDs.
- Feed-integrity audit: freshness, L2 coverage, aggressor-side delta coverage, timestamp ordering, and exchange-sequence continuity where available.
- Offline directional calibration for depth imbalance, aggressor delta, and absorption-reversal candidates.
- Wilson confidence intervals for calibrated directional accuracy.
- Shadow Microstructure Confirmation score for observability only.
- Promotion-readiness gate requiring minimum labeled observations, evidence coverage, timestamp integrity, and measured predictive accuracy.
- Operator approval flag is visible but cannot by itself activate production behavior.

## New endpoints
- `GET /api/microstructure/integrity`
- `GET /api/microstructure/calibration`
- `GET /api/microstructure/promotion-readiness`
- `GET /api/microstructure/shadow-confirmation`
- `POST /api/microstructure/outcomes`

## Configuration
- `MICROSTRUCTURE_PROMOTION_MIN_LABELED` default `100`
- `MICROSTRUCTURE_PROMOTION_MIN_ACCURACY_PCT` default `55`
- `MICROSTRUCTURE_PROMOTION_MIN_COVERAGE_PCT` default `95`
- `MICROSTRUCTURE_PROMOTION_APPROVED` default `false`; review metadata only in 68.9 and never an activation switch.

## Governance
- No future outcome is used in a live decision.
- No automatic promotion.
- No decision-confidence mutation.
- No execution authority.
- `production_effect = NONE` throughout 68.9.
- Real L2/MBO observations and explicit outcome labels are required; aggregate bars remain ineligible.

## Next gate
A later build may connect **approved, statistically supported** microstructure evidence to the canonical decision-evidence contract, initially as a bounded canary/shadow comparison. That must occur only after live ES depth collection produces sufficient labeled samples and the 68.9 readiness gates pass.
