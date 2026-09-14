# APEX 69.10.11 — Immutable Historical Evidence Archive & Dependency-Preserving Projection Foundation

## Objective

APEX 69.10.10 established that historical Trigger Observatory `evidence_json` and Evidence Pipeline `snapshot_json` contain substantial historical amplification, but it also source-verified active consumers that make destructive in-place compaction unsafe. 69.10.11 adds the migration foundation required before any historical rewrite can be considered.

## Implementation

### Immutable archival sidecar

`engine/historical_payload_archive.py` introduces `apex_historical_payload_archive.db` as an additive sidecar. The archive stores:

- payload type and canonical row identity;
- source table/column provenance;
- original observation timestamp;
- original byte count and SHA-256;
- zlib level-9 compressed original payload bytes;
- archive byte count and archival timestamp;
- APEX and archive schema versions;
- integrity state.

The sidecar is content-addressed and identity constrained. A canonical identity that is presented with a different source hash fails closed. SQL `BEFORE UPDATE` and `BEFORE DELETE` triggers make archived rows immutable even if a caller bypasses the Python API.

### Exact round-trip integrity

Archive retrieval decompresses the stored payload and verifies both the original SHA-256 and original byte count. Historical source payloads are therefore recoverable byte-for-byte before any later lossy projection is authorized.

### Bounded operator archive

The operator maintenance CLI adds dry-run-first actions for archive planning, archive status, bounded Trigger Observatory archiving, bounded Evidence Pipeline snapshot archiving, and shadow validation. Archive population requires explicit `--apply`; there is no automatic population.

When the archive destination filesystem is at the canonical CRITICAL storage threshold, archive writes fail closed with `STORAGE_CRITICAL_ARCHIVE_WRITE_BLOCKED`. This prevents an emergency storage condition from being worsened by copying historical data into the sidecar before disk capacity is increased.

### Shadow validation foundation

Shadow validation compares the canonical full payload with the compact projection and exact archival fallback. It reports archive misses, projection errors, exact archive matches, and whether the sampled rows are shadow-read ready. Production readers are not redirected and no runtime consumer behavior changes in 69.10.11.

### Compaction readiness ratchet

The 69.10.10 readiness state is advanced from “sidecar not implemented” to:

`FOUNDATION_IMPLEMENTED_AWAITING_ARCHIVE_AND_SHADOW_VALIDATION`

Historical rewrite remains disabled. Source-verified consumers of full/fallback payloads continue to block destructive compaction until archive population and shadow validation prove dependency preservation.

## Guardrails

69.10.11 does **not**:

- rewrite or delete canonical Trigger Observatory rows;
- rewrite or delete canonical Evidence Pipeline decisions;
- redirect production reads;
- perform mass archive population automatically;
- perform historical compaction;
- VACUUM active databases;
- promise filesystem reclaim;
- change grading, calibration, attribution, learning, trade decisions, risk, execution authority, or broker behavior.

## Operator commands

Read-only plan:

```bash
python scripts/apex_storage_maintenance.py payload-archive-plan
```

Archive status:

```bash
python scripts/apex_storage_maintenance.py payload-archive-status
```

Bounded dry-run archive:

```bash
python scripts/apex_storage_maintenance.py archive-trigger-payloads --limit 25
python scripts/apex_storage_maintenance.py archive-decision-payloads --limit 25
```

Explicit bounded archive, only after storage capacity is no longer CRITICAL:

```bash
python scripts/apex_storage_maintenance.py archive-trigger-payloads --limit 25 --apply
python scripts/apex_storage_maintenance.py archive-decision-payloads --limit 25 --apply
```

Read-only shadow validation:

```bash
python scripts/apex_storage_maintenance.py shadow-validate-trigger-payloads --limit 25
python scripts/apex_storage_maintenance.py shadow-validate-decision-payloads --limit 25
```

## Verification classification

### Source verified

- archival writes are additive only;
- SQL update/delete triggers enforce archive immutability;
- exact source SHA-256 and byte count are persisted and checked on retrieval;
- archive identity/hash conflicts fail closed;
- explicit apply is required for archive population;
- CRITICAL storage capacity blocks archive writes;
- shadow validation never redirects production reads;
- canonical historical rows remain untouched.

### Test verified

See `APEX_69_10_11_BUILD_REPORT.md` for test, compile, architecture-integrity, and configuration-governance results.

### Runtime verified

Not yet. Production verification requires deployment of 69.10.11 and inspection of `/api/admin/storage/audit`, `payload-archive-plan`, archive status, and bounded shadow-validation output. No production archival or compaction result is claimed by this source build.
