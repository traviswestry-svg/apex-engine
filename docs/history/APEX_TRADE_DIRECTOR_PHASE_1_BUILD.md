# APEX Trade Director — Phase 1

## Added
- Expanded active-trade management hero after manual `I'M IN` confirmation.
- Displays ticker, direction, contracts, SPX entry/current level, option entry/current premium, estimated open P/L, trade health, recommendation, and confidence.
- Displays concise reasons for the current HOLD / TRIM-PROTECT / EXIT directive.
- Adds manual live-premium synchronization so P/L can be updated before broker position synchronization is enabled.
- Preserves the existing trim, breakeven, close, and clear controls.

## API changes
- Active positions now track `option_current_price`.
- `/api/position` returns `trade_health`, `confidence`, `unrealized_pnl`, `unrealized_pnl_pct`, and `underlying_move_in_favor`.
- `/api/position/action` accepts `UPDATE_PREMIUM` with `option_current_price`.

## Safety and stability
- Manual controls record state only and do not transmit broker orders.
- No scanner, startup worker, scheduled task, or import-time workload was added.
- Preserve the stable Render environment settings.

## Validation
- `python -m py_compile app.py` passed.
- 30 Active Trade Director tests passed.
