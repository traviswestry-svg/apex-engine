# APEX Trade Director Phase 31 Build

## Institutional Evidence & Outcome Validation

Phase 31 converts actionable Trade Director recommendations into immutable, point-in-time evidence records and grades those records only from supplied SPX OHLC bars. It is a measurement layer, not a policy or execution layer.

## Repository truth and scope

The repository contained Phases 28–30 and several legacy learning/replay modules, but no unified immutable 0DTE decision ledger that captured the full feature vector at decision time and graded the resulting SPX path. Phase 31 fills that specific gap without replacing existing learning, replay, governance, lineage, allocation, or execution-certification architecture.

## Added

- `engine/trade_director_institutional_evidence.py`
- `tests/test_trade_director_phase31.py`
- Phase 31 dashboard panel in `templates/assistant.html`
- Phase 31 coordinated-scan integration and API routes in `app.py`

## Evidence model

SQLite database: `APEX_EVIDENCE_DB`, falling back to `/data/apex_evidence.db` on writable Render persistent storage or `./apex_evidence.db` locally.

Tables:

- `apex_evidence_decisions` — immutable point-in-time decision snapshots
- `apex_evidence_outcomes` — immutable SPX-bar grades
- `apex_evidence_events` — append-only integrity chain

Database triggers reject updates and deletes to all evidence records.

## Automatic capture boundary

The coordinated Trade Director scan calls Phase 31 after Phase 30. Automatic persistence occurs only for actionable states:

- `ARMED`
- `EXECUTE`
- `ENTER`
- `AUTHORIZED`

Non-actionable states remain uncaptured unless an explicit manual API request uses `force=true`. Direction must resolve to CALL/PUT, LONG/SHORT, or BULLISH/BEARISH.

Captured fields include:

- decision ID, trade ID, timestamp, symbol, state and direction
- confidence, entry, stop, target and grading horizon
- full feature vector
- confidence/engine attribution
- complete source snapshot
- Phase 28 lineage ID when available
- SHA-256 snapshot hash

Duplicate scans are idempotent.

## Outcome grading

`POST /api/evidence/grade` requires a decision ID and real OHLC bars. It calculates:

- target and stop results
- maximum favorable excursion
- maximum adverse excursion
- realized SPX points
- exit time, exit price and exit reason
- WIN, LOSS, FLAT or AMBIGUOUS grade

When a stop and target both occur inside the same bar and tick order is unavailable, Phase 31 records `AMBIGUOUS_SAME_BAR_STOP_FIRST` and uses the conservative stop-first result. It never fabricates intrabar ordering.

## Calibration

Phase 31 reports empirical results in confidence bands:

- 0–49
- 50–74
- 75–84
- 85–100

Each band reports sample count, win rate, average realized points, average MFE and average MAE. Confidence monotonicity is evaluated only after at least 10 samples populate two or more bands.

No engine weight or threshold is changed automatically. Policy review remains blocked until at least 100 outcomes are graded.

## API endpoints

- `GET /api/evidence/status`
- `GET /api/evidence/decisions`
- `GET /api/evidence/decision/<decision_id>`
- `POST /api/evidence/capture`
- `POST /api/evidence/grade`
- `GET /api/evidence/calibration`
- `GET /api/evidence/integrity`

## Dashboard

The `/assistant` surface now includes an Institutional Evidence & Outcome Validation panel showing:

- decisions captured, outcomes graded and coverage
- confidence-band results
- integrity state
- latest captured decisions
- evidence gates and the 100-outcome threshold

The panel explicitly shows that automatic weight updates and policy mutation are off.

## Safety boundary

Phase 31:

- does not place or modify broker orders
- does not authorize execution
- does not adjust risk
- does not alter engine weights
- does not promote policy
- does not synthesize market bars or outcomes

## Validation results

- Python compilation: **PASS** (`python -m compileall -q .`)
- Phase 31 focused tests: **9 passed, 0 failed**
- Trade Director Phase 13–31 regression slice: **78 passed, 0 failed**
- Broader executable regression set: **1,009 passed**
- Environment-blocked broader checks: **3**, all caused by missing `flask` in the execution environment
- Dashboard JavaScript syntax: **PASS** (`node --check`)
- Static API registration: **PASS** — seven Phase 31 routes present in `app.py`
- ZIP integrity: validated after packaging

### Environment limitation

The repository declares Flask as an application dependency, but Flask is not installed in the provided build container. Therefore live Flask app import, Flask test-client endpoint execution, and Flask-dependent test collection could not be honestly reported as passing. This is an environment limitation, not a substituted pass.

## Deployment notes

1. Deploy the complete repository or changed-files package.
2. Ensure normal repository dependencies are installed by the Render build command.
3. For persistent evidence on Render, attach persistent storage at `/data` or set `APEX_EVIDENCE_DB` to a persistent SQLite path.
4. Confirm `/api/evidence/status` after deployment.
5. During a live session, verify an actual ARMED/EXECUTE decision appears in `apex_evidence_decisions`.
6. Feed authoritative 1-minute SPX bars into `/api/evidence/grade` after the configured horizon or cash close.

## Changed files

- `app.py`
- `engine/trade_director_institutional_evidence.py`
- `templates/assistant.html`
- `tests/test_trade_director_phase31.py`
- `APEX_TRADE_DIRECTOR_PHASE_31_BUILD.md`
