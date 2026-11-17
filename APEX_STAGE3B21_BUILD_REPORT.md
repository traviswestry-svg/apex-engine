# APEX Stage 3B.2.1 — Build Report

**Scope:** Archive Payload-Budget Attribution & Bounded Correspondence Recovery

## Production motivation

Stage 3B.2's 2026-11-17 production audit sampled eight DECISION_SNAPSHOT and eight TRIGGER_EVIDENCE records. Only one trigger record passed byte-exact correspondence; fifteen reported the undifferentiated `PAYLOAD_BUDGET_EXCEEDED`. These results do not establish corruption, loss, mismatches, or archival completeness.

## Root cause in predecessor implementation

The predecessor combined per-record compressed/uncompressed size limits with an aggregate budget state and charged its global budget using `source_bytes` after a source lookup without recording which representation was charged. It could continue emitting ambiguous exhaustion states, and a size estimate was insufficient to identify whether the archive's historic payloads exceeded the cap.

## Candidate behavior

- Opens existing immutable archive and source SQLite databases in `mode=ro` + `PRAGMA query_only=ON`. No new archives or copies are created.
- Obtains bounded, ordered archive *metadata* before materializing an archive BLOB or source payload.
- Classifies `ARCHIVE_COMPRESSED_LIMIT_EXCEEDED`, `ARCHIVE_UNCOMPRESSED_LIMIT_EXCEEDED`, `GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED`, `ARCHIVE_METADATA_INVALID`, and `ACTUAL_SOURCE_LIMIT_EXCEEDED` independently.
- Charges three explicit representations for each attempted comparison: compressed archive bytes + decompressed bytes + source-canonical bytes. These are conservative **reservations based on metadata**, not actual resident memory or I/O measurements.
- Skips an oversized individual record and continues to smaller records in the same bounded sample. Stops all subsequent records/types when global byte reservation is exhausted; operation/time budgets are also bounded cooperatively.
- Fetches archive BLOB with SQL `substr` cap and source bytes with SQL `substr` cap. Checks integrity, UTF-8, byte equality, and parsed JSON projection. **Not full historical engine replay**.
- Emits counts and aggregate budget reservations only: no archived identifiers, raw content, hashes, sampled record sizes, or paths to source rows.
- Continues to mark migration `BLOCKED_RESEARCH_ONLY` and provides no production reader cutover or retention authorization.

## Bounded usage

```bash
python scripts/apex_stage3b21_budget_recovery_audit.py \
  --root /data \
  --sample-rows 8 \
  --query-budget-ms 400 \
  --total-budget-ms 6000 \
  --max-payload-bytes 262144 \
  --raw-byte-budget 1048576 \
  --output /tmp/apex-stage3b21-budget-recovery.json
```

```bash
cat /tmp/apex-stage3b21-budget-recovery.json
```

Output must be outside `/data`. The query/time safeguards are *cooperative* and cannot bound OS I/O waits; run off-market.

## Validation

- **19 focused tests passed** against temporary synthetic SQLite fixtures.
- Byte-exact source/archive match and JSON projection; trigger evidence; mismatches; missing/null source; invalid UTF-8; integrity; oversize compressed and inflated metadata; global exhaustion; negative metadata; no identifier export; no SQLite data writes; and migration authority blocking.
- Full APEX integration CI and production run: **not performed**.

## Remaining gates

Historical production replay, cross-database gamma/decision identity, reader cutover coverage, exhaustive correspondence, external backup/restore test, isolated rollback, representative performance, and Stage 3B.1 invalid-UTF-8 reader-fix verification remain unverified. This candidate cannot authorize migration.
