# APEX Trade Director Phase 28

## Institutional Data Integrity & Lineage

Phase 28 adds an append-only provenance and integrity layer to the coordinated Trade Director stack.

### Added

- `engine/trade_director_data_lineage.py`
- Immutable SQLite lineage ledger and relationship graph
- Payload and chained integrity hashes
- Source, dataset, engine-version, confidence, and parent ancestry metadata
- Integrity verification and tamper detection
- Decision/trade lineage tree and audit export
- Lineage Explorer dashboard panel
- `/api/lineage/*` API family
- `tests/test_trade_director_phase28.py`

### API

- `GET /api/lineage/event/<lineage_id>`
- `GET /api/lineage/decision/<trade_id>`
- `GET /api/lineage/tree/<trade_id>`
- `GET /api/lineage/integrity`
- `GET /api/lineage/history`
- `POST /api/lineage/verify`
- `POST /api/lineage/export`
- `POST /api/lineage/register`

### Integrity states

- `VERIFIED`
- `WARNING`
- `FAILED`
- `TAMPER_DETECTED`

### Safety boundary

Phase 28 is audit-only. It cannot alter strategy, risk, authorization, lifecycle, governance, execution, or broker orders.
