# APEX Trade Director Phase 32 Build

## Performance & Calibration Center

Phase 32 converts immutable Phase 31 decision/outcome evidence into read-only empirical performance analytics. It does not add a new directional engine and cannot change live confidence, thresholds, policy, risk, authorization, or broker state.

## Repository truth and scope

Phase 31 already captured point-in-time actionable decisions and graded them from supplied SPX OHLC bars. The repository did not yet provide a unified center for realized expectancy, confidence reliability, session/direction breakdowns, engine contribution analysis, or an auditable graded-decision ledger. Phase 32 fills that gap only.

## Added

- `engine/trade_director_performance_calibration.py`
- `tests/test_trade_director_phase32.py`
- Phase 32 dashboard panel in `templates/assistant.html`
- Phase 32 coordinated-scan integration and five API routes in `app.py`

## Analytics provided

### Realized performance

- graded sample count
- win rate
- average realized SPX points
- average MFE and MAE
- profit factor
- ambiguous outcome count
- breakdown by CALL/PUT or directional label
- breakdown by decision state
- Eastern Time session buckets

### Confidence calibration

- empirical predicted-versus-realized win rates by confidence band
- Brier score
- expected calibration error
- confidence monotonicity test
- 100-graded-decision review gate

### Engine attribution

Phase 32 reads the immutable engine attribution captured with each Phase 31 decision and provides:

- samples per engine
- median contribution score
- high-score versus low-score performance
- descriptive expectancy lift
- per-engine sample gate

The method is explicitly labeled `MEDIAN_SPLIT_DESCRIPTIVE_NOT_CAUSAL`. Correlated engines are not represented as independent causal evidence.

### Decision ledger

The ledger exposes graded decisions with:

- immutable decision and outcome identifiers
- timestamp, state, direction and confidence
- entry, stop, target and exit
- grade, exit reason, MFE, MAE and realized points
- grading method and bar count
- snapshot and outcome hashes

Direction and grade filters are supported.

## API endpoints

- `GET /api/performance-calibration/status`
- `GET /api/performance-calibration/performance`
- `GET /api/performance-calibration/calibration`
- `GET /api/performance-calibration/attribution`
- `GET /api/performance-calibration/ledger`

## Dashboard integration

The `/assistant` page now includes a Performance & Calibration Center showing:

- realized win rate and expectancy
- MFE and MAE
- Brier score and calibration error
- confidence reliability bands
- confidence monotonicity state
- top engine attribution summaries
- evidence and sample-size blockers
- immutable read-only governance controls

## Evidence gates

- 100 valid graded decisions before calibration review readiness
- 30 samples per engine before engine attribution is labeled ready
- 10 samples in at least two confidence bands before monotonicity is evaluated
- ambiguous same-bar outcomes are excluded from binary calibration scoring

## Safety boundary

Phase 32:

- is read-only
- does not update engine weights
- does not change confidence thresholds
- does not promote policy
- does not alter risk or authorization
- has no broker access
- does not fabricate decisions, outcomes, feature values, or statistics

## Validation results

- Python compilation: **PASS** (`python -m compileall -q .`)
- Phase 32 focused tests: **6 passed, 0 failed**
- Trade Director Phase 13–32 regression suite: **84 passed, 0 failed**
- Dashboard JavaScript syntax: **PASS** (`node --check`)
- Static dashboard integration: **PASS**
- Static API registration: **PASS** — five Phase 32 routes present
- ZIP integrity: validated after packaging

### Full-suite environment limitation

The complete repository test run could not collect because Flask is absent from the provided build container. Pytest reported 42 collection errors, all caused by `ModuleNotFoundError: No module named 'flask'` in Flask-dependent test modules. These checks are documented as environment-blocked and are not counted as passes.

## Deployment notes

1. Deploy the complete Phase 32 repository or the changed-files package.
2. Preserve the Phase 31 evidence database using Render persistent storage at `/data` or `APEX_EVIDENCE_DB`.
3. Confirm `/api/evidence/status` is collecting and grading decisions.
4. Confirm `/api/performance-calibration/status` returns `COLLECTING_EVIDENCE` until sample gates are met.
5. No calibration values should be used to change policy until governed review and shadow validation are completed.

## Changed files

- `app.py`
- `engine/trade_director_performance_calibration.py`
- `templates/assistant.html`
- `tests/test_trade_director_phase32.py`
- `APEX_TRADE_DIRECTOR_PHASE_32_BUILD.md`
