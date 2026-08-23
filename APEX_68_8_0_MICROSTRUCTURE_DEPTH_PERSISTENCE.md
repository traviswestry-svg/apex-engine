# APEX 68.8.0 — Market Microstructure Depth Integration & Liquidity Persistence

## Purpose

68.8 advances the 68.7 observation-only microstructure foundation into a real-feed ingestion boundary with bounded persistence. It does **not** fabricate DOM/MBO from candles, aggregate futures bars, or SPX index data. A licensed ES/MES depth bridge must publish normalized L2 or MBO observations into APEX.

## Added

- Provider-neutral normalized depth ingestion: `POST /api/microstructure/ingest`
- Strict rejection of aggregate-bar/proxy payloads at the ingestion boundary
- Automatic prior-book attachment for add/pull/replenishment comparison
- SQLite-backed bounded depth history with WAL
- Rolling aggressor-classified CVD from persisted trade evidence
- Historical liquidity persistence/heatmap state
- Runtime state/history/heatmap endpoints
- Feed capability/configuration governance that distinguishes code readiness from actual live feed evidence

## Endpoints

- `GET /api/microstructure/capability`
- `GET /api/microstructure/health`
- `POST /api/microstructure/analyze`
- `POST /api/microstructure/ingest`
- `GET /api/microstructure/state?instrument=ES`
- `GET /api/microstructure/history?instrument=ES&limit=120`
- `GET /api/microstructure/heatmap?instrument=ES&limit=240&min_persistence=0.05`

All routes remain under the existing APEX application-wide authentication layer.

## Required feed contract

The external bridge must identify a concrete licensed source and provide:

- `instrument`: `ES` or `MES`
- `source`: concrete provider/feed name
- `feed_quality`: `L2` or `MBO`
- `observed_at`
- `book.bids[]` and `book.asks[]` with price + size
- `trades[]` with price, size, and `aggressor_side` for true delta/CVD
- optionally `order_events[]`, `order_id`, and exchange sequence fields for MBO-grade reconstruction

## Configuration

- `MICROSTRUCTURE_INGEST_ENABLED=true` enables the mutation boundary.
- `MICROSTRUCTURE_FEED_PROVIDER=<licensed provider/bridge name>` identifies the configured source.
- `MICROSTRUCTURE_DB_PATH=<path>` overrides the default `data/market_microstructure.sqlite3`.
- `MICROSTRUCTURE_MAX_SNAPSHOTS` defaults to `12000` per instrument.
- `MICROSTRUCTURE_MAX_AGE_MINUTES` defaults to `480` minutes.

## Governance

68.8 remains advisory/shadow-only:

- `production_effect = NONE`
- `influences_decision = false`
- `execution_authority = false`
- Microstructure Confirmation Score remains disabled pending real feed collection and calibration.
- MBO/iceberg authority is not claimed from L2 data.

## Next gate

68.9 should only promote microstructure into calibrated decision evidence after enough real ES observations exist to validate freshness, sequence integrity, CVD continuity, liquidity persistence, absorption/exhaustion behavior, and outcome attribution.
