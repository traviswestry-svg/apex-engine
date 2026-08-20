# APEX 68.1.0 — Calibration & Trigger Learning Closure

## Scope closed

- Intraday horizon conflicts are governed to the same-snapshot canonical session direction. The raw independent classification remains available for diagnostics; Swing remains an independent higher-timeframe context.
- Gross call/put premium is no longer labeled directional accumulation/distribution without qualifying tape and order-flow confirmation.
- Learning Assistant style-fit values are explicitly identified as heuristic 0–100 scores, separate from graded-trade sample counts and minimum sample requirements.
- BPSPX uses the real Polygon `I:BPSPX` series as the primary refresh path while retaining TradingView breadth alerts as a secondary source. Missing/stale observations remain fail-closed and are never inferred from SPX price.
- Every completed CALL/PUT Pine evaluation is promoted exactly once into the Phase 22 ledger as `SIMULATED_TRIGGER_TRADE`. Stable IDs and sync state make the bridge idempotent and retryable after restarts or transient Phase 22 failures.

## Safety boundaries

- Simulated trigger trades are not represented as broker fills.
- Horizon intelligence remains advisory and has no execution authority.
- Missing BPSPX caps context confidence and cannot create direction.
- Exit/outcome scoring remains based on the configured SPX forward-evaluation window.

## Validation

- Python compilation passed for the changed Python modules and new regression test.
- Direct regression checks passed for canonical intraday governance, unconfirmed premium classification, Learning Assistant score semantics, and idempotent Phase 22 simulated-trade promotion.
- The attached environment did not include `pytest`; the pytest suite was added but could not be executed through the absent test runner.
