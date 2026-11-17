# APEX Stage 3B.1 — Immutable Archive Reader Compatibility & Historical Replay Verification

## Scope and source

- Based on `apex-engine-main(20261112-221036).zip` (offline source snapshot, **not** a claim of production source parity).
- Targets existing `engine/historical_payload_archive.py`, `retrieve_archived_payload`, `_decompress`, `DECISION_SNAPSHOT`, and `TRIGGER_EVIDENCE`.
- **No production SQLite file accessed**. Only synthetic SQLite fixtures are written to temporary directories; cleanup is automatic.
- **No archive backfill, production reader cutover, migration, VACUUM, checkpoint, schema change, or trading authority change.**

## Implementation

- `scripts/apex_stage3b1_archive_replay_audit.py`: inspects source, extracts the existing archive reader/decompressor function definitions without importing APEX application modules, exercises them against isolated SQLite fixture archives, and produces a JSON report with pass/fail behavior and read-path source hints.
- `tests/test_apex_stage3b1_archive_replay_audit.py`: twelve focused tests, including contract-bound synthetic restoration, error paths, guardrails, and optional patch evaluation.
- `patches/OPTIONAL_ARCHIVE_INVALID_UTF8_FAIL_CLOSED.patch`: a separately reviewed *optional* reader-only correction for an invalid UTF-8 failure path. **NOT applied automatically.**
- `stage3b1_offline_report.json`: source-snapshot audit result.

## Verified findings

- Synthetic decision and trigger evidence are restored byte-for-byte by the original reader, including JSON key ordering and a synthetic gamma identity.
- Missing row, stored-hash mismatch, wrong recorded byte length, truncated zlib blob, and unsupported codec return failure results in the existing reader.
- **Failure found:** a zlib stream containing bytes with valid recorded hash and size but invalid UTF-8 causes an **uncaught `UnicodeDecodeError`** in `retrieve_archived_payload`. This is a synthetic fault-injection result, not evidence of corrupted production records.
- Original reader: **8/9** synthetic behavioral checks pass; optional isolated patch: **9/9** pass.
- **12/12** Stage 3B.1 candidate unit tests pass.
- 421 engine Python files scanned for bounded lexical read-path hints. This is not a complete call graph and does not establish actual reader or writer compatibility.
- Production archive/source correspondence, historical replay, backup restore, rollback, and live-reader cutover **remain unverified**.

## Run after integrating into repository

```bash
python scripts/apex_stage3b1_archive_replay_audit.py \
  --repo-root . \
  --output /tmp/apex-stage3b1-compatibility.json
```

The script returns exit status **2** if it finds a reader failure path or a missing source contract. For the unpatched November 12 source, exit status 2 with `status=BLOCKED_READER_FAILURE_PATHS` is the expected safety outcome, not a crash.

```bash
python -m unittest discover -s tests -p 'test_apex_stage3b1_archive_replay_audit.py' -v
```

The optional patch should be applied only after independent source-version review and CI. Even with the fix, the audit status is `RESEARCH_ONLY_GATES_UNVERIFIED`, and migration remains `BLOCKED_RESEARCH_ONLY`. The patch alone does **not** authorize live reader cutover or modification of stored archives.

## Next gates

1. Confirm against the **current deployed source**, not only the November 12 snapshot.
2. Validate full production reader/writer call graph and every affected field.
3. Verify source/archive byte-for-byte identity on an **isolated restored copy** with controlled access (no raw evidence export).
4. Run deterministic historical replay, gamma identity, and settlement attribution comparisons on that isolated copy.
5. Demonstrate external backup recovery and rollback independently.
6. Benchmark representative reader latency, memory, and failure handling.
7. Obtain explicit human approval for any future migration.
