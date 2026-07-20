# APEX 26.0 — Execution Intelligence Core / Execution Director (CHANGELOG)

First sprint of the APEX 26.x Institutional Execution Intelligence line. It is
the advisory brain for HOW to execute a 25.x decision. ADVISORY ONLY — it never
places, previews-and-confirms, or submits an order. Built on the completed
25.5 delta (assumes 25.0-25.5 deployed).

## Added
- `engine/execution_intelligence_core_v260.py` — the Execution Director:
  * Execution readiness (READY / NOT_READY / BLOCKED): non-eligible decisions are
    NOT_READY (wait); wide spread / stale quote are hard BLOCKED. READY never
    means auto-trade — human confirmation is always required.
  * Strategy selection (directional debit / debit spread / stand down).
  * Entry & order-quality optimization (patience vs chase, MARKET / LIMIT /
    LIMIT_OFFSET, expected slippage, entry confidence).
  * Position sizing that ENFORCES the existing RiskLimits (max_contracts,
    max_risk_per_trade) with a capped Kelly fraction that can only reduce size.
  * Exit framing (advisory initial stop / target / breakeven).
  * Execution grading independent of forecast (slippage-based, NOT_GRADEABLE
    without a fill).
- `engine/execution_intelligence_core_v260_routes.py` — six advisory routes.
- `tests/test_execution_intelligence_core_v260.py` — 21 engine tests.
- `tests/test_execution_intelligence_core_v260_routes.py` — 9 route tests.

## Modified
- `app.py` — fail-loud import + registration for 26.0 (mirrors 25.x).

## Reuse (no duplication) & safety
- Reads the existing `engine/execution/trade_risk_guard.RiskLimits` for sizing.
- Emits recommendations that flow into the EXISTING confirmation-gated execution
  path (`engine/execution/trade_routes`). 26.0 adds no order-placement code and
  no broker calls. `places_orders` False; `production_effect` NONE everywhere.
- No new environment variables; no new database.

## Scope note
26.0 is the Execution Director spine. The remaining 26.x components — full
Contract Intelligence (26.2), Liquidity/Slippage (26.3), Dynamic Trade
Management (26.5), Trade Story (26.6), Broker Intelligence (26.7), Execution
Review (26.8), Command Center (26.9), Trader Mode (26.10) — follow as their own
deltas, each behind the same confirmation gate.
