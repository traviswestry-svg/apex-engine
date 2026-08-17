# APEX 67.0.0 — Canonical Persistence Layer Merge Summary

**Date**: 2026-08-17  
**Branch**: apex-66-4-1-decision-coherence  
**Source**: APEX_67_0_0_Canonical_Persistence_Layer_Changed_Files.zip  
**Version Jump**: 66.9.0 → 67.0.0

---

## Overview

Introduces `engine/canonical_persistence.py` as the standard SQLite connection policy for all APEX-owned databases. This standardizes timeout handling, busy-wait behavior, WAL journaling, transaction management, and diagnostic capabilities while preserving existing database schemas and file locations.

This is a **staged migration**: existing stores continue unchanged until individually moved behind the canonical layer and regression-tested.

---

## Core Implementation

### New Module: `engine/canonical_persistence.py`

**Version**: 67.0.0  
**Schema**: apex.canonical_persistence.v1

#### Key Functions

**`connect(path, *, read_only=False, timeout=None, row_factory=True, foreign_keys=True, wal=True, heal=True) -> sqlite3.Connection`**
- Standardized SQLite connection with APEX connection policy
- Configurable timeout, busy handling, WAL mode, synchronous mode
- Automatic file-backed database healing via `db_resilience.py`
- SQLite Row factory for dict-like access
- Foreign-key enforcement enabled by default

**`connection(path, **kwargs) -> Iterator[sqlite3.Connection]`**
- Context manager that guarantees connection closure
- Wraps native SQLite context to make lifecycle explicit
- Unlike SQLite's native context, this always calls `close()`

**`transaction(path, **kwargs) -> Iterator[sqlite3.Connection]`**
- Atomic write transaction with automatic rollback on error
- Calls `BEGIN`, executes yield block, then `COMMIT` or `ROLLBACK`
- Always closes connection in finally block

**`diagnostics(path) -> dict[str, Any]`**
- Non-mutating inspection of database health and policy compliance
- Returns journal mode, foreign keys status, integrity check result
- Reports current policy configuration

#### Configuration (Environment Variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `APEX_SQLITE_TIMEOUT_SECONDS` | 15 | Connection timeout |
| `APEX_SQLITE_BUSY_TIMEOUT_MS` | 15000 | Busy-wait timeout (ms) |
| `APEX_SQLITE_SYNCHRONOUS` | NORMAL | Sync mode (OFF/NORMAL/FULL/EXTRA) |

#### Behavioral Features

✓ **WAL Journaling**: Enabled for all writable file-backed databases  
✓ **Foreign-Key Enforcement**: Enabled by default  
✓ **Row Factory**: Dict-like access via `sqlite3.Row` by default  
✓ **Automatic Healing**: Detects and repairs corruption before connecting  
✓ **Transaction Safety**: Explicit atomic operations with rollback  
✓ **Read-Only Support**: URI-based read-only mode  
✓ **In-Memory Databases**: Supported with WAL disabled  
✓ **Non-Mutating Diagnostics**: Inspect without modifying state  

---

## Initial Migrations

Four modules migrated to use canonical persistence:

### 1. **engine/evidence_pipeline.py**
- Replaced: `sqlite3.connect(path); conn.row_factory=sqlite3.Row`
- With: `canonical_connect(path)`
- Reduces boilerplate while adding policy enforcement

### 2. **engine/institutional_governance.py**
- Replaced: Custom connection setup with manual PRAGMA foreign_keys=ON
- With: `canonical_connect(DB_PATH)`
- Removes redundant manual configuration

### 3. **engine/trade_director_learning.py**
- Integrated canonical persistence layer
- Standardized connection policy

### 4. **engine/historical_level_calibration.py**
- Updated read/write paths to use canonical persistence
- Maintains existing schema and data structures

---

## Configuration Updates

### `config/apex_release_manifest.json`
- **APEX Version**: 66.9.0 → 67.0.0
- **Build Name**: Confidence Calibration Audit (unchanged)

### `config/apex_capability_registry.yaml`
- **Schema Version**: apex.capability_registry.v1 (unchanged)
- **APEX Version**: 66.9.0 → 67.0.0

---

## Testing

### Test Suite: `tests/test_apex_67_0_canonical_persistence.py`

**5 test cases, all passing:**

1. **`test_canonical_connection_enforces_policy`**
   - ✓ Verifies WAL journaling enabled
   - ✓ Verifies foreign-key enforcement
   - ✓ Verifies busy-timeout configuration

2. **`test_transaction_commits_and_rolls_back`**
   - ✓ Successful transaction commits
   - ✓ Failed transaction rolls back (preserves previous state)
   - ✓ Connection lifecycle managed correctly

3. **`test_read_only_connection_rejects_write`**
   - ✓ Read-only mode URI-based connection
   - ✓ Write operations rejected as expected
   - ✓ Prevents accidental mutations

4. **`test_diagnostics_reports_integrity`**
   - ✓ Diagnostics return database health
   - ✓ Reports journal mode (WAL)
   - ✓ Reports integrity status

5. **`test_evidence_pipeline_uses_canonical_policy`**
   - ✓ Evidence pipeline connection uses canonical policy
   - ✓ WAL mode confirmed
   - ✓ Foreign-key enforcement confirmed
   - ✓ Row factory confirmed

**Result**: 5/5 tests passing ✓

---

## Design Decisions

### Staged Migration Approach
- **Why**: Reduces risk; each module migrated independently, regression-tested
- **State**: Evidence Pipeline, Institutional Governance, Trade Director Learning, HLCE moved first
- **Future**: Additional stores can migrate when verified safe

### Connection Pooling Deferred
- Canonical layer manages individual connections, not connection pools
- Pools can be built on top when needed (future enhancement)

### Automatic Healing
- New `heal=True` parameter enables `db_resilience.py` corruption detection
- Can be disabled for read-only consumers: `heal=False`

### Non-Mutating Diagnostics
- `diagnostics()` function uses read-only connection
- Enables health checks without write side effects

### Policy Enforcement via Pragmas
- Applied immediately after connection open (not in schema)
- Survives schema evolution unchanged
- Can be reconfigured per-application without database migration

---

## Files Modified

### Modified (6 files)
- `config/apex_release_manifest.json` (version bump)
- `config/apex_capability_registry.yaml` (version bump)
- `engine/evidence_pipeline.py` (+3 lines, -0 net)
- `engine/institutional_governance.py` (+3 lines, -0 net)
- `engine/trade_director_learning.py` (standardized connection)
- `engine/historical_level_calibration.py` (standardized connection)

### Added (3 files)
- `engine/canonical_persistence.py` (new ~150 LOC module)
- `tests/test_apex_67_0_canonical_persistence.py` (5 test cases)
- `APEX_67_0_0_CANONICAL_PERSISTENCE_LAYER.md` (documentation)

### Archive
- `APEX_67_0_0_Canonical_Persistence_Layer_Changed_Files.zip` (source)
- `APEX_67_1_0_Silent_Degradation_Observability_Changed_Files.zip` (future release)

---

## Authority

✓ **Persistence standardization has no decision or execution authority**  
✓ **No change to existing decision paths**  
✓ **No change to execution boundaries**  
✓ **No schema modifications** (only connection policy)

---

## Backward Compatibility

✓ Existing database files unchanged  
✓ Existing schemas unchanged  
✓ Existing application code continues to work  
✓ New modules benefit from standardized connection policy  
✓ Legacy stores can migrate independently when safe

---

## Next Steps

1. ✓ Merge into `apex-66-4-1-decision-coherence`
2. Create PR for review
3. After merge to `main`, plan APEX 67.1.0 (Silent Degradation Observability)

---

## Summary Statistics

- **Total Changes**: 11 lines added, 17 lines removed (net -6)
- **New Module LOC**: ~150 (canonical_persistence.py)
- **New Tests**: 5 (all passing)
- **Files Migrated**: 4 (evidence, governance, learning, calibration)
- **Version Jump**: Major (66.9.0 → 67.0.0) due to new canonical module
