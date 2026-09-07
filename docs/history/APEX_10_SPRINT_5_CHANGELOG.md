# APEX 10 — Sprint 5 / Phase 7

## Learning and Calibration

Added leakage-safe outcome scoring, confidence calibration reports, bounded policy proposals, and explicit policy promotion.

### New modules
- `engine/learning_calibration.py`
- `engine/learning_routes.py`

### Outcome scoring
- `TARGET_FIRST` and `TARGET_ONLY` map to successful binary calibration targets.
- `STOP_FIRST` and `STOP_ONLY` map to unsuccessful targets.
- `NEITHER`, simultaneous, unknown-order, and missing outcomes are excluded from binary calibration rather than guessed.

### Calibration metrics
- Brier score
- Expected calibration error
- Reliability bins comparing predicted confidence with settled success rate

### Controlled learning
- Chronological, session-disjoint train/evaluation splits are mandatory.
- Minimum usable samples: 100 train and 50 evaluation.
- Parameter movement is bounded to 10%.
- Promotion requires at least 0.005 out-of-sample Brier improvement.
- Proposals are persisted as `PROPOSED`; automatic activation is prohibited.
- Promotion is an explicit API action and retires the prior active policy.

### Confidence integration
`confidence_attribution` now reports:
- `effective_confidence` before learned calibration
- `learned_calibration`
- `calibrated_confidence`
- policy ID and parameters when a promoted policy is active

The original directional decision remains unchanged.

### API
- `GET /api/learning/calibration`
- `POST /api/learning/proposals`
- `POST /api/learning/policies/<policy_id>/promote`
- `GET /api/learning/outcomes/<sample_id>`
- `GET /api/learning/apply?confidence=...`

### Validation
- 584 tests passed
- 0 failed
