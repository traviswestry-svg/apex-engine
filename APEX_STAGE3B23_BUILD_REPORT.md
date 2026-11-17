# APEX Stage 3B.2.3 — Build report

## Objective
Bounded, operator-initiated read-only comparison of large immutable archive payloads with canonical source JSON and sampled archive format provenance. This is an incremental diagnostic, **not** a production migration, full replay, or reader cutover.

## Source and approach
Grounded in the November 12, 2026 APEX source snapshot (`engine/historical_payload_archive.py`), and the existing Stage 3B.2.1 and 3B.2.2 candidate scripts. Existing immutable `ZLIB_9` codec retained. No runtime APEX imports or side effects.

- Oldest and newest N records per evidence type (default 2 each; maximum 4 each).
- Metadata validation before fetching either archive blob or source content; declared per-record cap <= 1.5 MiB, globally reserved budget <= 16 MiB.
- Counts archive compressed, decompressed and source canonical bytes in the **reservation budget**; does not claim to measure actual memory or I/O.
- Requires index-supported source identity lookup; compares archive/source timestamps.
- Bounded decompression with EOF/trailing-data checks, stored compressed length, declared raw length and SHA-256 verification.
- Tests byte-exact archived/source UTF-8 payload equality and valid JSON top-level type as a **payload projection**; does not replay trading engine.
- Reports only aggregate status counts, version labels (sanitized), and top-level JSON shape categories. No identifiers, raw JSON, hashes, keys or example values in output.
- No SQLite write, checkpoint, delete, VACUUM, archiving, read path changes or execution authority.

## Run
After integration, review, full CI and deployment, execute from Render Shell **outside market hours**:

```bash
python scripts/apex_stage3b23_large_payload_provenance_audit.py \
 --root /data --sample-rows 2 --query-budget-ms 400 \
 --total-budget-ms 10000 --max-payload-bytes 1572864 \
 --raw-byte-budget 16777216 \
 --output /tmp/apex-stage3b23-large-payload.json
cat /tmp/apex-stage3b23-large-payload.json
```

Per-query and total time budgets are cooperative SQLite progress-handler limits; blocked I/O and compression CPU are not hard timed. Larger historical data or live contention may cause bounded interruptions. If data differs mid-audit, report failure, not proof of corruption.

## Validation performed
- New Stage 3B.2.3 unit tests: **16 passed**.
- Earlier Stage 3B.2.1 and Stage 3B.2.2 candidate tests: **35 passed** (ResourceWarnings from their fixture connection cleanup; no failures).
- **51 selected tests passed**, full repository CI **not executed**.
- No production database tested or modified in this build.

## Known limitations
- Oldest/newest samples are not population-representative, and source records might change between separate read-only connections.
- Source identity/time checks are not a full cross-database canonical gamma verification.
- `source_bytes` and `archive_bytes` are trusted to preflight, then validated after materialization; inflated output is capped independent of metadata.
- JSON structure scope is restricted to top-level object/list/scalar type, rather than logging key names or detailed schema.
- Stored hash verifies archived bytes and exact source comparison verifies sampled correspondence only. No complete historical APEX engine replay.
- Stage 3B.1 invalid UTF-8 reader fix, external backup restore, rollback and production reader coverage remain unverified.

**Migration authority: `BLOCKED_RESEARCH_ONLY`**.
