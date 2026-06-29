# APEX 6.3.2 Changelog — Institutional Flow Tape

**Sprint:** 6.3.2  
**Date:** 2026-06-28  
**Status:** Production

## New Features

### engine/flow_tape.py (NEW)
- `build_flow_tape()` — normalizes raw QuantData consolidated order-flow rows
- Classification: ABOVE_ASK/AT_ASK → BUY aggressor; AT_BID/BELOW_BID → SELL aggressor
- Tape labels: BUY_SWEEP / SELL_SWEEP / BUY_BLOCK / SELL_BLOCK / BUY_SPLIT / SELL_SPLIT / UNKNOWN
- Importance scoring (0–100) based on premium size, aggression, and consolidation type
- Premium extraction handles all known QuantData field name variants
- Summary: buy_premium, sell_premium, net_premium, sweep_count, block_count, tape_bias
- Proper terminology: "Institutional Options Flow Tape" — NOT DOM, NOT cumulative delta

### app.py — /api/flow_tape (NEW)
- GET /api/flow_tape?tickers=SPY,QQQ,SPX,NVDA,TSLA&min_premium=250000&size=50
- Returns classified tape rows + summary
- Graceful fallback if QuantData not configured
- Circuit breaker aware

### /apex_os — Institutional Flow Tape panel (NEW)
- Bottom panel visible on main terminal view
- Filter buttons: All / Sweeps / Blocks / SPY/QQQ/SPX / Tech
- Summary bar: buy/sell premium, net, sweep count, block count, tape bias
- Table: time, ticker, type, strike, expiry, premium, label/importance
- Auto-refresh every 45 seconds (+ on each OS load)
- Color coded: green rows = BUY, red rows = SELL

### /api/institutional_os — Flow Tape Integration
- Fetches tape summary (SPY/QQQ/SPX) on each institutional_os call
- Adds `flow_tape_summary` and `flow_tape_rows_preview` to response

### engine/__init__.py
- Exports `build_flow_tape`

## Notes
- Flow tape does not break dashboard if QuantData returns no rows
- `_fetch_flow_tape_rows()` is circuit-breaker aware
- min_premium default: $250,000
