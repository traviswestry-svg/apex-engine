# APEX Trade Director Phase 4 — Institutional Position Intelligence

## Added

- Exit Probability Engine
  - continuation and reversal probability
  - estimated remaining SPX move to the active objective
  - HOLD, PROTECT PROFIT, TRIM 50%, or EXIT/REDUCE guidance
- Multi-Timeframe Alignment
  - 1m, 3m, 5m, 15m, and 30m cache-aware alignment
  - missing readings remain explicitly unavailable
- Adaptive Stop Engine
  - evaluates cached EMA 8, VWAP, market structure, and value-area levels
  - recommends only a tighter valid stop; never sends a broker order
- Live Risk Meter
  - open P/L, estimated capital at risk, remaining reward, and remaining R/R
- Opportunity Cost Monitor
  - compares the active trade with existing cached scanner/heatmap candidates
  - never starts a scan or new market-data request
- Phase 4 safety governor
  - may make the current management recommendation more protective
  - cannot upgrade a defensive recommendation into a riskier action

## Stability guarantees

Phase 4 adds no startup workload, worker threads, scanners, timers, provider calls, or broker execution. It consumes the existing position state and Institutional OS cache.

## Validation

- `python -m py_compile app.py`
- 60 Active Trade Director tests passed

## Changed files

- `app.py`
- `templates/assistant.html`
- `APEX_TRADE_DIRECTOR_PHASE_4_BUILD.md`
