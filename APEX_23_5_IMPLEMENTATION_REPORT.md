# APEX 23.5 — Institutional AI Trading Coach

Release identity: `16.5.0_INSTITUTIONAL_AI_TRADING_COACH`

## Implemented
- Advisory pre-trade coaching: TAKE, REDUCE_SIZE, or STAND_DOWN.
- Daily-loss, trade-count, anti-chase, risk/reward, regime, forecast, evidence-conflict, and human-confirmation checks.
- Active-trade lifecycle coaching: HOLD, PROTECT, REDUCE_RISK, EXIT, and DO_NOT_ADD guidance.
- TP1/TP2 protection logic, thesis invalidation, stop, and maximum-hold controls.
- Post-trade behavioral review separating strategy quality from execution quality.
- Rule-adherence, entry, stop, and profit-management scorecards.
- Immutable sanitized review persistence and optional explicit handoff of matured outcomes to APEX 23.4.
- Mission Control Trading Coach group and drill-down.
- Seven read/write-safe coach endpoints.

## Safety
The coach is advisory only. It cannot place or preview orders, change stops, modify risk limits, override kill switches, or automatically feed learning outcomes without an explicit request.
