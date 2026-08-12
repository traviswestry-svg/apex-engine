# APEX 66.4.0 — Trade Horizon Intelligence & Dashboard Classification

## Objective
Make APEX explicitly identify the market trend and trade focus for three independent horizons: SCALP, INTRADAY, and SWING. Prevent evidence intended for one holding horizon from silently dominating another.

## Added
- `engine/trade_horizon_intelligence.py`
  - Canonical read-only horizon classifier.
  - Independent SCALP / INTRADAY / SWING trend, bias, trade focus, confidence, coverage, supporting evidence, and opposing evidence.
  - Explicit source-relevance matrix so microstructure, flow, auction, session structure, daily structure, macro regime, and cross-asset evidence carry different authority by horizon.
  - Countertrend/with-trend scalp relationship classification.
  - Fail-closed `DATA_LIMITED / NO_TRADE` behavior.
  - No execution authority.
- `GET /api/trade-horizon-intelligence`
  - Returns latest composed horizon intelligence without provider fan-out.
- Persistent Trade Horizon Intelligence band on `/apex_os`
  - SCALP: 15s–5m / 1–5 min.
  - INTRADAY: 5m–65m / 15–120 min.
  - SWING: 65m–Daily / multi-day.
  - Shows trend, trade focus, confidence, readiness/data-limited status, and horizon relationship.
  - Responsive stacking for mobile/small screens.
- Automated tests in `tests/test_trade_horizon_intelligence.py`.

## Guardrails preserved
- Horizon intelligence is advisory/read-only.
- It does not place, route, approve, or modify orders.
- Existing confirmation, risk, Trade Director, and broker gates retain authority.
- Sub-minute data is not granted independent directional authority.
- Insufficient horizon evidence resolves to UNKNOWN / DATA_LIMITED / NO_TRADE.

## Release identity
Canonical APEX release updated from 66.3.2 to 66.4.0.
Build name: `Trade Horizon Intelligence & Dashboard Classification`.

## Validation
- `python -m py_compile engine/trade_horizon_intelligence.py app.py engine/release_manager.py` — PASS
- `node --check static/js/apex_os.js` — PASS
- `pytest -q tests/test_trade_horizon_intelligence.py tests/test_trade_director_phase39.py` — 8 PASS
- Existing Flask-dependent multi-timeframe test could not be collected in this local container because the `flask` package is not installed; this is an environment dependency issue, not a failing assertion.
