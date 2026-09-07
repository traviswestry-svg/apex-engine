# APEX Trade Director Phase 21 — Institutional Trade Lifecycle Engine

Phase 21 introduces the first formal integrated lifecycle layer. It consumes the outputs of the established context, strategy, contract, decision, risk, and execution engines rather than creating an independent trading opinion.

## Added

- `engine/trade_director_lifecycle_contracts.py`
  - Normalized shared `TradeContext` envelope
  - Dependency-light helpers
  - No I/O or startup behavior
- `engine/trade_director_trade_lifecycle.py`
  - Coordinated lifecycle states
  - Thesis-aware hold, protect, scale, runner, and exit decisions
  - Immediate defensive changes
  - Stable-repeat requirement for less-defensive promotion
  - Provenance from Phases 14, 16, 17, 18, and 20
- `GET/POST /api/position/trade-lifecycle`
- Institutional Trade Lifecycle dashboard panel
- Phase 21 deterministic unit tests

## Lifecycle states

- `DECISION_AUTHORIZED`
- `ENTRY_PENDING`
- `POSITION_ACTIVE`
- `PROTECT`
- `SCALE`
- `RUNNER`
- `EXIT`
- `DECISION_BLOCKED`

## Management actions

- `WAIT_FOR_ENTRY`
- `PROCEED_TO_PHASE10_PREVIEW`
- `WAIT_FOR_FINAL_CONFIRMATION`
- `HOLD_POSITION`
- `TIGHTEN_RISK`
- `TAKE_PARTIAL_AND_PROTECT`
- `SCALE_AND_TRAIL`
- `REDUCE_AND_TIGHTEN`
- `EXIT_POSITION`
- `STAND_DOWN`

## Authority and safety

Phase 21 is advisory. It cannot contact providers or brokers, submit/modify/cancel orders, bypass Phase 9 risk controls, bypass Phase 10 exact confirmation, widen risk beyond the governed plan, or override upstream `STOP_TRADING`/`STAND_DOWN` authority.

No new environment variables or startup processes are required.
