# APEX Trade Director Phase 9 — Execution Readiness & Risk Guardrails

## Purpose
Phase 9 converts the stable Phase 8 management policy into a broker-neutral, confirmation-ready action preview while enforcing deterministic risk guardrails. It remains advisory and never sends, modifies, or cancels a broker order.

## Added
- `engine/trade_director_execution_readiness.py`
- Contract-aware trim/exit quantity calculation
- Current and remaining premium exposure estimates
- Estimated remaining long-option maximum loss
- Configurable per-trade, daily-loss, contract, and daily-trade limits
- Blocking and warning checks
- Stale-preview protection using deterministic preview IDs
- Preview acknowledgement/rejection audit trail
- Phase 9 panel on `/assistant`

## API
- `GET /api/position/execution-readiness`
- `POST /api/position/execution-readiness/decision`

## Optional environment variables
- `APEX_MAX_CONTRACTS` (default `3`)
- `APEX_MAX_TRADE_RISK` (default `2000`)
- `APEX_MAX_DAILY_LOSS` (default `1000`)
- `APEX_MAX_DAILY_TRADES` (default `3`)

## Safety
- Execution is hard-disabled.
- No broker adapter is called.
- No market-data request, scanner, worker, timer, or startup job was added.
- Preview acknowledgement records an audit event only.

## Validation
- `app.py` compiled successfully.
- Phase 9 module compiled successfully.
- Assistant JavaScript passed `node --check`.
- 60 Active Trade Director tests passed across both test-suite copies.
- Phase 9 ready and blocked guardrail smoke tests passed.
