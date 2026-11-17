# APEX Stage 3B.2 — Historical Archive-to-Source Correspondence & Replay Equivalence Audit

## Scope
Opt-in, read-only bounded inspection of production `/data` SQLite **decision snapshot** and **trigger evidence** archived rows. No production migration, no historical engine replay, and no reader cutover. Extends Stage 3B.1 research; does not apply the optional invalid-UTF8 reader patch.

## Inspected basis
November 12, 2026 `apex-engine-main(20261112-221036).zip`, including `engine/historical_payload_archive.py` with `ZLIB_9`, `historical_payload_archive(payload_type,row_id,source_table,source_column,source_sha256,source_bytes,archive_codec,archive_blob,archive_bytes,...)`, `decisions.snapshot_json` and `observed_trade_triggers.evidence_json`. Stage 3B.1's candidate and audit reviewed.

## Files
- `scripts/apex_stage3b2_archive_source_replay_audit.py` — standalone audit CLI, stdlib only.
- `tests/test_apex_stage3b2_archive_source_replay_audit.py` — isolated SQLite fixture tests.
- `INTEGRATION_MANIFEST.json` — placement and execution information.

## Detection and protections
- Uses read-only SQLite URI (`mode=ro`) and `PRAGMA query_only=ON` for archive and both canonical sources. No implicit archive initialization or import of APEX production modules.
- Samples up to 8 latest archived rows **per payload type**, maximum 32; uses `rowid DESC` and bounded `substr` on BLOB columns. Each canonical lookup uses the identity column and bounded BLOB output.
- Applies cooperative SQLite progress callbacks, per-query and total query budgets, decompression output limits, and a global payload processing cap. Note: Python and SQLite timing is not a hard bound on OS disk I/O or a query's pending file lock.
- Verifies compressed codec, compressed byte length, decompressed byte length, SHA-256 checksum, exact original UTF-8 bytes and JSON projection equivalence (on parsed payload). Reports aggregate counts only: no identifiers, payload values, hashes or source JSON keys.
- Detects missing source row, null or changed source, bad codec, corrupt archive, invalid UTF-8, and incompatible archive source metadata.
- Archive exact-byte checks and parsed JSON projection equivalence are **not equivalent to historical APEX engine replay, settlement verification, feature timing, or production reader cutover**. They cannot independently validate gamma IDs across databases.
- No SQL writes, inserts, updates, deletes, `VACUUM`, checkpoint, database copying or migration.

## Validation
17 Stage 3B.2 focused fixture tests passed. Full APEX CI and live production execution **not performed**. No source/database mutations performed.

## Remaining migration gates (always blocked)
- Stage 3B.1 malformed UTF-8 archive reader behavior may still need its optional patch.
- Full historical APEX replay equivalence and cross-database gamma/decision identity.
- Exhaustive archive/source correspondence and production reader coverage.
- Production-representative benchmark and verified backup/restore/rollback in an isolated environment.

## Production diagnostic usage (after code review, CI and deployment)
```bash
python scripts/apex_stage3b2_archive_source_replay_audit.py \
  --root /data \
  --sample-rows 8 \
  --query-budget-ms 400 \
  --total-budget-ms 6000 \
  --max-payload-bytes 262144 \
  --raw-byte-budget 1048576 \
  --output /tmp/apex-stage3b2-correspondence.json
```
Output MUST remain outside `/data`. Inspect result with `cat /tmp/apex-stage3b2-correspondence.json`.

## Status
**RESEARCH-ONLY / MIGRATION BLOCKED.** A clean sample is not authorization to change archival formats or delete original evidence.
