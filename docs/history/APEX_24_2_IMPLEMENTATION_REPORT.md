# APEX 24.2 — Institutional Replay & Simulator

Release identity: `17.2.0_INSTITUTIONAL_REPLAY_SIMULATOR`

## Summary

Reconstructs the exact historical decision environment across every
institutional engine rather than recalculating from current market data. A
captured session is an immutable, integrity-hashed snapshot of the outputs of the
Trading Brain, Regime Intelligence, Forecast Engine, Playbook Engine, Trading
Coach, Execution Intelligence, and Portfolio Intelligence (24.1), plus Market
Memory references and a read-only Continuous Learning view. Trade-level decision
replay reuses the existing APEX 14 `institutional_replay_2` engine (decision-time
only, look-ahead blocked).

## Reuse, not duplication

Every engine output is produced by that engine's existing `build_*` function;
this module performs no market recalculation of its own. Decision replay reuses
`institutional_replay_2`. Portfolio inputs reuse APEX 24.1
`build_portfolio_intelligence`.

## Implemented

- Immutable session capture (`capture`) assembling the full multi-engine
  environment; re-capture with the same `session_key` returns the existing record.
- Deterministic, ordered timeline (`timeline`) following the canonical event
  order: MARKET_STATE, SIGNAL_GENERATION, REGIME_TRANSITION, FORECAST_UPDATE,
  PLAYBOOK_UPDATE, COACH_RECOMMENDATION, ENTRY_APPROVAL, TRADE_MANAGEMENT, EXIT,
  OUTCOME. Each event carries timestamp, source engine, rationale, supporting
  evidence, and contradicting evidence.
- Trade replay (`trade`): entry thesis, market structure, supporting/conflicting
  evidence, risk parameters, execution score, coach guidance, and outcome; reuses
  the decision-time replay when a `decision_id` is present.
- Session navigation (`navigate`): PLAY, PAUSE, STEP_FORWARD, STEP_BACKWARD,
  JUMP_TIMESTAMP, JUMP_TRADE, JUMP_REGIME_TRANSITION — pure functions over the
  immutable frames.
- What-if simulator (`simulate`): ALTERNATIVE_PLAYBOOK, ALTERNATIVE_SIZING,
  ALTERNATIVE_EXITS. Advisory comparison on frozen inputs; it writes nothing and
  never modifies historical records (`history_modified: false`,
  `records_written: 0`).
- Mission Control: `REPLAY_SIMULATOR` panel + `/api/replay/status` drill-down.

## API surface (one canonical namespace)

Owned by APEX 24.2: `GET /api/replay/status`, `GET /api/replay/session`,
`GET /api/replay/trade`, `GET /api/replay/timeline`, `POST /api/replay/simulator`,
plus supporting `POST /api/replay/capture` and `GET /api/replay/navigate`.

Backward compatible: `GET /api/replay/session` now dispatches by parameter —
`session_id` addresses the 24.2 reconstruction, while the legacy intraday index
(`?ticker=&date=`) is preserved by delegating to the original app.py handler
(demoted from a route to a helper). `GET /api/replay/frame` and the roadmap
narrative-replay routes (`/narrative`, `/consensus`, `/thesis`, `/decision`) are
untouched.

## Registrar hardening

Registration runs outside the broad non-fatal block, verifies all five canonical
routes, and fails loudly (`RuntimeError`) on missing or duplicate routes.

## Safety

Read-only and advisory. Historical snapshots are immutable and integrity-hashed.
The simulator is isolated (no writes to session tables). Nothing here places,
modifies, or cancels orders, resizes positions, or bypasses kill switches. Live
replay contains no look-ahead outcome information.
