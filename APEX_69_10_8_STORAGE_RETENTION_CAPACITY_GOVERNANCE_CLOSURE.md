# APEX 69.10.8 — Storage Retention & Capacity Governance Closure

## Scope

APEX 69.10.8 is an operations-only storage safety build. It does not change trade decisions, execution authority, flow learning, calibration authority, scanner cadence, replay-frame freshness, or canonical evidence semantics.

The production trigger for this build was persistent-disk free capacity falling to 12.93% while top-level `/health` still reported `WARNING`. The existing governed storage-retention audit already treated free capacity below 15% as `CRITICAL`. Two separate threshold policies therefore described the same disk differently.

## Closure

### 1. Canonical capacity policy

`engine/storage_capacity_policy.py` is now the shared source for persistent-storage thresholds:

- WARNING: free space <= 25% by default
- CRITICAL: free space <= 15% by default
- canonical configuration: `APEX_STORAGE_WARN_FREE_PCT` / `APEX_STORAGE_CRITICAL_FREE_PCT`
- legacy `APEX_DISK_WARN_FREE_PCT` / `APEX_DISK_CRITICAL_FREE_PCT` remain supported as fallback configuration

`engine.operational_runtime.storage_status()` and `engine.storage_retention.audit()` now use the same classifier, so `/health` and the storage audit cannot disagree solely because of different built-in thresholds.

### 2. Database footprint audit

The authenticated read-only storage audit now reports, for each active SQLite database when available:

- file size
- page count and page size
- freelist pages
- SQLite-internal reusable bytes
- largest SQLite objects/tables via `dbstat`
- largest databases ranked by file size

The audit explicitly distinguishes SQLite reusable pages from filesystem bytes. A SQLite `DELETE` may make pages reusable without returning disk capacity to the operating system.

### 3. Capacity governance plan

The storage audit emits explicit operator actions when capacity is constrained. At CRITICAL capacity the first action is to increase persistent-disk capacity rather than attempt a risky in-place VACUUM.

Eligible quarantined corrupt databases and WAL bytes are reported separately. Mature evidence price-sample pruning remains bounded by the oldest pending decision.

### 4. Operator-governed maintenance CLI

`scripts/apex_storage_maintenance.py` provides four bounded operations:

- `audit`
- `checkpoint-wals`
- `cleanup-quarantine`
- `prune-price-samples`

Dry-run is the default. Mutating maintenance requires explicit `--apply`.

No operation VACUUMs an active database. No operation deletes canonical decisions, grading results, flow features, excursion evidence, calibration evidence, or raw trigger-observation evidence.

### 5. Existing read-only API preserved

`GET /api/admin/storage/audit` remains authenticated and read-only. It never invokes a maintenance mutator. Its schema version is now `apex.storage_audit.v2`.

## Important non-goals

69.10.8 does not automatically delete data to recover capacity. It does not add automatic trigger-observation pruning. It does not promise filesystem recovery from evidence price-sample deletion. It does not change active SQLite database files with unlink or VACUUM operations.

The production audit after deployment should be used to determine which tables are responsible for `apex_trigger_observatory.db`, `apex_evidence_pipeline.db`, `apex_calibration.db`, and `apex_tracking.db` growth before any future retention policy is expanded.
