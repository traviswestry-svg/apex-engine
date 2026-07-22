# APEX Trade Director Phase 12 — Institutional Intelligence & Market Memory

## Added
- Lazy SQLite market-memory archive
- Historical session similarity engine
- Probability distribution engine
- Institutional playbook library
- Sample-aware confidence calibration
- Predictive session planner
- Lookahead-protected replay endpoint
- Missed-opportunity journal
- Knowledge-graph foundation metadata
- Phase 12 dashboard panel

## Endpoints
- `GET /api/position/market-memory`
- `POST /api/position/market-memory/archive`
- `GET /api/position/market-memory/replay`
- `GET|POST /api/position/market-memory/missed-opportunity`

## Safety
Phase 12 is research and planning only. It does not start workers, call providers, scan markets, connect to a broker, or transmit orders. Phase 9 and Phase 10 remain authoritative for risk and execution.

## Optional environment variable
- `APEX_MARKET_MEMORY_DB=/data/apex_market_memory.db`
