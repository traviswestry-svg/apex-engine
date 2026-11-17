# APEX Stage 3B.0 — Lossless Evidence Compression Compatibility & Storage Migration Feasibility

**Build status:** OFFLINE RESEARCH CANDIDATE; NOT A PRODUCTION MIGRATION. 2026-11-17.

## Source basis

Examined local user-provided `apex-engine-main(20261112-221036).zip` (November 12 snapshot), and Stage 3A.3 production aggregate audit output provided November 17. The source snapshot predates the November 17 production audit/deploy. Differences with the current production commit are **not verified**.

### Important existing implementation

APEX already contains `engine/historical_payload_archive.py` (immutable sidecar archive, `ZLIB_9`, SHA-256 integrity, retrieve function, explicit `DECISION_SNAPSHOT` and `TRIGGER_EVIDENCE` types) and `engine/historical_payload_compaction.py` (conservative dependency definitions and rewrite blockers). Stage 3B.0 deliberately does **not** create a new archive schema, replace these modules, call their mutating methods, or redirect readers.

`engine/evidence_pipeline.py` reads `decisions.snapshot_json` inline; `engine/feature_store_db.py` reads `flow_features.features_json` / `availability_json` inline; `engine/gamma_transition.py` parses inline `snapshot_json` and `lineage_json`; `engine/level_transition_probability.py` parses `target_cluster_json`; `engine/trigger_observatory.py` reads inline evidence and canonical grades. Static hints require manual verification for exhaustive reader/writer coverage, especially dynamic SQL and external consumers.

## New additive files

- `scripts/apex_stage3b0_compatibility_audit.py`: offline-only bounded local source reference inventory, existing archive contract detection, and synthetic zlib6/zlib9 byte-exact benchmark; JSON report with hard migration blockers. **Never opens production SQLite**.
- `tests/test_apex_stage3b0_compatibility_audit.py`: correctness, bounded decompression, corrupt/trailing stream, source inventory, and no authorization tests.
- This report and `INTEGRATION_MANIFEST.json`.

## Validation

- 21 new Stage 3B.0 tests PASSED.
- 32 existing repository tests PASSED (storage/retention, decision storage amplification, canonical gamma evidence identity): **53 selected tests passed overall**. Full CI **not run**.
- Ran the new standalone audit against the user-provided November 12 source: 421 engine Python files; 96,803 source lines scanned; inventory complete within specified 1,200 file / 100,000 line limits. Source hints are **not** verified ownership or dependency closure.
- Synthetic fixtures: 5 shapes, byte-exact round-trips for zlib level 6 and level 9 with bounded decode, median per-operation latency and peak `tracemalloc` bytes. Results are synthetic and **not** production performance, storage savings, or proof of historical equivalence.

## Deployment and execution

No deployment is necessary to analyze the included source snapshot. If a fresh code inventory is wanted, add only `scripts/apex_stage3b0_compatibility_audit.py` into APEX; run from the repo root:

```
python scripts/apex_stage3b0_compatibility_audit.py \
  --repo-root . \
  --output /tmp/apex-stage3b0-compatibility.json
```

The script never reads `/data`, never opens SQLite, and refuses writing reports inside the repository or `/data`. Does not register endpoints, jobs, timers, trading routes or migrations.

## Mandatory Stage 3B gates (ALL BLOCKED)

1. Complete reader/writer coverage across engine, integrations, APIs, historical replays, and external consumers; code-reference matches are hints, not proof.
2. Establish *byte-exact* restoration of actual immutable historical payloads through all legacy read paths, preserving order/format/UTF-8, not just semantic JSON equality.
3. Validate decision-time evidence, gamma identity, grade provenance, paper-only execution mode, and settlement attribution equivalence in isolated fixtures.
4. Demonstrate archive sidecar source-hash conflict behavior, integrity/immutability, missing/corrupt archive fail-closed logic, and version fallback using nonproduction databases.
5. Verify point-in-time external backups and perform an isolated successful restore.
6. Measure real CPU, latency, peak memory and disk effects over representative nonproduction data; include writes, WAL, indexes, sidecar overhead, and reclaim mechanics.
7. Produce an explicit, independently approved rollback plan; no production dual-writes, reader redirection, migrations, deletes, VACUUM, checkpoint or archive backfill in this release.

## Decision

`BLOCKED_RESEARCH_ONLY`. Existing archive warrants compatibility hardening and read-path integration research **before** any new codec or production migration proposal. No deletion, retention, migration, or execution authority is granted.
