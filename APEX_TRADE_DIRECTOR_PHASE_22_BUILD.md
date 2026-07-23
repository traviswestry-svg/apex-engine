# APEX Trade Director Phase 22 — Institutional Learning & Adaptive Intelligence

## Purpose
Phase 22 closes the coordinated trade lifecycle by converting completed Phase 21 trades into durable institutional learning. It is an advisory feedback layer and does not alter live execution, risk, authorization, or management controls.

## Delivered
- Institutional Learning Ledger with lazy SQLite persistence
- Canonical market, decision, execution, outcome, and learning contexts
- Decision-quality evaluation
- Confidence calibration by probability bucket
- Strategy scorecards and expectancy analysis
- Engine evidence attribution
- Historical trade-similarity retrieval
- Advisory feedback contract for Phases 14, 15, 19, 20, and 21
- Institutional Learning Center dashboard
- Read, evaluate, archive, and history API routes

## API
- `GET /api/position/institutional-learning`
- `POST /api/position/institutional-learning`
  - `action: ARCHIVE_OUTCOME`
  - `action: EVALUATE`
- `GET /api/position/institutional-learning/history?limit=100`

## Persistence
Phase 22 reuses `APEX_TRADE_LEARNING_DB` when configured. Otherwise it uses `/data/apex_trade_learning.db` on writable Render persistent storage or a local repository database during development.

No database is opened at import time. Schema creation is lazy on the first Phase 22 ledger operation.

## Safety
Phase 22 cannot:
- contact providers or brokers
- submit, cancel, replace, or modify orders
- change Phase 9 risk limits
- bypass Phase 10 confirmation
- override Phase 20 authorization
- override Phase 21 management
- automatically retrain or promote live models
- automatically alter strategy weights or confidence thresholds

All findings remain advisory. Findings are marked provisional until adequate comparable samples exist.

## Validation
- Python compilation passed
- Architecture audit passed
- Dashboard JavaScript syntax passed
- Phase 13–22 regression suite passed
- Database resilience test passed
- 47 tests passed
