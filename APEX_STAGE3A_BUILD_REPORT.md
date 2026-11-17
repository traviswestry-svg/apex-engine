# APEX Stage 3A — SQLite Database Growth, Storage Capacity & Safe Retention Audit

**Candidate only; not deployed.** Based on uploaded `apex-engine-main(20261112-221036).zip`. Runtime version remains **69.10.47**, manifest unchanged. The user's latest production `/health` observations were supplied November 16, 2026 (20:42 ET); this tool has **not** accessed `/data` in production.

## Context from last production snapshot

- Persistent storage **24.6531% free**, **1,293,475,840 available bytes** of 5,246,713,856 bytes (25% warning crossed; operator action required).
- Active/sidecar DB footprint total reported **3,923,245,960 bytes**.
- Largest DBs: tracking 1,304,199,168; evidence pipeline 1,009,156,096; trigger observatory 685,076,480; calibration 576,065,536 bytes.
- Memory-limit event history is separate from disk capacity: 804 cumulative `memory.events.max`, no newly observed events in a single-sample worker baseline, zero OOM kills.

## Source review and overlap avoidance

Existing `engine/storage_capacity_policy.py` already implements canonical 25%/15% capacity thresholds. Existing `engine/storage_retention.py` and `scripts/apex_storage_maintenance.py` already include governed audit, retention, and **explicit-apply** maintenance options. Their existing `audit()` can issue full-table `COUNT(*)`, `MIN`/`MAX`, decision payload attribution, and whole-file `dbstat` aggregation. Stage 3A **does not duplicate/change those maintenance entrypoints**, install new workers, or run as a `/health` side effect. A *standalone low-I/O* metadata collector is supplied for operator use.

## New files

- `scripts/apex_stage3a_storage_audit.py`: read-only standalone collector. Defaults to `/data` but accepts `--root`; never modifies DB/schema or executes checkpoints; inspects at most 256 immediate files and up to 64 active DB metadata summaries. SQLite URI `mode=ro`, connection `query_only=ON`, and explicit connection close. Safely skips symlinks. Runs bounded metadata PRAGMAs `page_count`, `page_size`, `freelist_count`, `journal_mode`, and `sqlite_schema` type counts.
- `tests/test_apex_stage3a_storage_audit.py`: read-only, WAL/quarantine protection, budget, symlink, growth-comparison, capacity-threshold, output-location, and inventory-cap tests.

`--dbstat` is **explicit opt-in**; runs a budgeted group aggregation with a query progress handler (default 350 ms per DB, hard limit 2 s) and returns a bounded top 24 object list. Can be expensive on GB-scale databases and should run only under operator supervision outside busy scanning. Default audit skips table/index page-size scans.

The tool compares two externally saved snapshots (`--compare`) with matching roots and chronological timestamps. File growth, WAL changes, and filesystem free-space changes are reported without assuming a long-term growth rate. It does not count evidence rows or infer eligibility for deletion from file age. It makes no filesystem reclamation promise from SQLite freelist pages.

## Runbook

```bash
# Run from the application repository, outside of active peak workloads if possible.
python scripts/apex_stage3a_storage_audit.py --root /data --output /tmp/apex-stage3a-first.json

# Repeat at least several hours later; keep reports outside /data.
python scripts/apex_stage3a_storage_audit.py --root /data \
  --compare /tmp/apex-stage3a-first.json --output /tmp/apex-stage3a-second.json

# OPTIONAL: operator-controlled costly per-object scan, not routine /health work.
python scripts/apex_stage3a_storage_audit.py --root /data --dbstat \
  --query-budget-ms 350 --output /tmp/apex-stage3a-dbstat.json
```

Be aware that `/tmp` is not a durable storage location; securely export evidence reports to an approved external location for longitudinal tracking. Report output is refused inside `/data` to avoid aggravating the near-full volume. Comparing snapshots does not independently prove business retention eligibility.

## Evidence and safety gates before any Stage 3B

1. Expand persistent disk capacity or validate expansion and contingency if free space remains below the 25% warning threshold; do not wait until 15% critical.
2. Verify off-host, restorable backups and database consistency through an authorized operating process. This audit **does not verify backups**.
3. Confirm canonical-evidence ownership, pending states, linked outcomes/grades, reconciliation and archival obligations before any prune/retention modification.
4. Treat WAL and SHM as SQLite-managed active files: **never manually unlink**. No live `VACUUM`, no blind checkpoints, no filesystem cache purging.
5. Only propose Stage 3B after repeat snapshots and optional bounded object analysis indicate a specific safe target and CI/rollback plan.

## Validation

- **9** new Stage 3A tests passed.
- **26** existing storage-governance and retention tests passed.
- **32** selected gamma, settlement, consolidation, release-truth tests passed.
- **67** total selected tests passed.
- Full application CI was **not** run; no production files were accessed. Production response timing and large-file `dbstat` performance are unverified.
- No changes to release manifest, database schema, trading decisions, canonical evidence, broker execution, scanner scheduling, or automated maintenance.
