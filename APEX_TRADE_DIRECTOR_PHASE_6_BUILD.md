# APEX Trade Director Phase 6 — Learning, Replay & Calibration

## Added
- Durable, lazy SQLite archive of closed Trade Director positions.
- User-confirmed outcome capture; APEX does not infer broker fills.
- Recommendation-by-recommendation provisional scoring.
- Full trade replay with timeline, review, outcome and scoring.
- Historical trade archive endpoint.
- Learning scorecard by recommendation type.

## Endpoints
- `POST /api/position/outcome`
- `GET /api/position/replay?trade_id=...`
- `GET /api/position/history?limit=20`
- `GET /api/position/learning/scorecard`

## Stability
The learning database is initialized lazily only when a trade is archived or a Phase 6 endpoint is opened. No scanner, thread, provider call, scheduled task or broker action was added.

Default database path is `/data/apex_trade_learning.db` when Render's persistent disk is writable. Override with `APEX_TRADE_LEARNING_DB`.
