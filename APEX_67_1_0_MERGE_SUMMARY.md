# APEX 67.1.0 — Silent-Degradation Observability Merge Summary

**Date**: 2026-08-17  
**Branch**: apex-66-4-1-decision-coherence  
**Source**: APEX_67_1_0_Silent_Degradation_Observability_Changed_Files.zip  
**Version Jump**: 67.0.0 → 67.1.0

---

## Overview

Adds durable, structured visibility for non-fatal fallbacks and swallowed exceptions across APEX. When components encounter errors but recover via fallbacks, this captures evidence for diagnostics without interfering with the recovery path.

**Core principle**: The recorder is best-effort and must never become a new failure source.

---

## Core Implementation

### New Module: `engine/silent_degradation_observability.py`

**Version**: 67.1.0  
**Schema**: apex.silent_degradation_observability.v1  
**Default DB**: apex_degradation_events.db

#### Key Functions

**`record_degradation(*, component, operation, exc=None, severity="DEGRADED", fallback="UNKNOWN", decision_authority_suppressed=False, source=None, context=None) -> dict`**
- Records a single degradation event with best-effort semantics
- Never raises; all errors swallowed and logged to stdout only
- Falls back to in-memory ring if SQLite unavailable
- Deduplicates events by fingerprint (component+operation+exception+fallback)
- Updates occurrence_count on repeat

**`snapshot(limit: int = 100) -> dict`**
- Returns paginated degradation events (latest first)
- Includes aggregates: by_component, by_severity
- Returns source indicator: "SQLITE" or "MEMORY_FALLBACK"
- Reports status: "HEALTHY" (no events) or "DEGRADED"
- Non-mutating (read-only)

#### Captured Fields

| Field | Type | Purpose |
|-------|------|---------|
| fingerprint | str | SHA256[:20] of component+operation+exception+fallback (unique key) |
| first_seen | ISO8601 | When this degradation pattern was first detected |
| last_seen | ISO8601 | When this degradation pattern was last observed |
| component | str | Name of component experiencing degradation |
| operation | str | Name of operation that failed |
| severity | str | "DEGRADED", "CRITICAL", etc. |
| exception_type | str | Python exception class name or "NON_EXCEPTION_DEGRADATION" |
| message | str | Exception message (truncated to 1000 chars) |
| fallback | str | Description of fallback strategy used |
| decision_authority_suppressed | bool | Whether decision authority was suppressed due to this event |
| source | str | Where the degradation originated (optional) |
| context_json | JSON | Additional context for debugging |
| occurrence_count | int | How many times this exact degradation has occurred |

#### Safety Guarantees

✓ **Best-Effort Recording**: Errors in recording are logged to stdout, never raised  
✓ **Memory Fallback**: If SQLite unavailable, keeps ring buffer (~500 events default)  
✓ **Thread-Safe**: Uses RLock for in-memory buffer  
✓ **No Execution Authority**: Observer-only pattern  
✓ **Configurable**: Via environment variables  

#### Configuration (Environment Variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `APEX_DEGRADATION_DB` | apex_degradation_events.db | Database file path |
| `APEX_DEGRADATION_MEMORY_EVENTS` | 500 | Ring buffer size when SQLite unavailable |

---

## Routes & Dashboard

### New Routes Module: `engine/silent_degradation_observability_routes.py`

**`register_silent_degradation_observability_routes(app)`**
- Registers two Flask endpoints on the provided Flask app

**Routes**
- **API**: `GET /api/diagnostics/degradations?limit=100` → JSON snapshot
- **Dashboard**: `GET /apex_os/degradations` → HTML dashboard

### Dashboard Template: `templates/silent_degradation_observability.html`

- Real-time degradation event viewer
- Filters by component and severity
- Shows occurrence count and timestamps
- Displays fallback strategies used
- Highlights decision-authority-suppressed events

---

## Configuration Updates

### `config/apex_release_manifest.json`
- **APEX Version**: 67.0.0 → 67.1.0
- **Build Name**: Confidence Calibration Audit (unchanged)

### `config/apex_capability_registry.yaml`
- **APEX Version**: 67.0.0 → 67.1.0

---

## Integration Points

### `app.py` (~90 lines added)
- Registers silent degradation routes
- Wires `/api/diagnostics/degradations` and `/apex_os/degradations` endpoints
- Integrates with Flask app factory

### `scanner_worker.py` (~12 lines modified)
- Calls `record_degradation()` on fallback conditions
- Captures scanner collector-state fallbacks
- Uses HLCE canonical state provider fallback recording

### `templates/apex_os.html` (updated)
- Dashboard aggregation includes silent degradation section
- Links to degradations viewer
- Shows suppressed-authority event count

---

## Testing

### Test Suite: `tests/test_apex_67_1_silent_degradation_observability.py`

**3 test cases, all passing:**

1. **`test_records_and_deduplicates`**
   - ✓ Records same event twice
   - ✓ Deduplicates by fingerprint
   - ✓ Occurrence count incremented
   - ✓ Latest timestamp updated

2. **`test_memory_fallback_when_database_unavailable`**
   - ✓ When SQLite unavailable, records to memory ring
   - ✓ Snapshot returns MEMORY_FALLBACK source
   - ✓ No exception raised to caller

3. **`test_observability_has_no_execution_authority`**
   - ✓ Recorded events have "execution_authority": "NONE"
   - ✓ Cannot influence trading decisions
   - ✓ Decision-authority-suppressed flag tracked

**Result**: 3/3 tests passing ✓

---

## Initial Instrumentation

Six degradation capture points integrated:

1. **Canonical Market State Composition**
   - Fallback to EMPTY_CANONICAL_MARKET_STATE

2. **Flow Tape Provider**
   - Market-driver fallbacks recorded

3. **Execution-Governance Canonical Decision Provider**
   - Decision provider fallbacks tracked

4. **Active Trade Director Input Providers**
   - Input provider fallback events

5. **Range Intelligence Providers**
   - Range calculation fallbacks

6. **HLCE Scanner Collector-State Fallback**
   - Collector state reconstruction fallbacks

---

## Design Decisions

### Best-Effort Pattern
- Recording never blocks or raises
- Database unavailability doesn't cascade
- In-memory fallback ensures capture
- Stdout logging for observability failures

### Fingerprint-Based Deduplication
- SHA256[:20] of (component, operation, exception, fallback)
- Unique per degradation type
- Enables efficient aggregation
- Allows grouping similar failures

### No Schema Dependency
- Uses canonical_persistence for connections
- Flexible JSON context storage
- Can add instrumentation without migrations

### Decision-Authority Suppression Tracking
- Boolean flag per event
- Indicates whether trading authority was suppressed
- Enables critical-issue alerting

### Memory Fallback Ring
- Configurable size (~500 default)
- Acts as circuit-breaker if DB fails
- Automatic downgrade, no human intervention
- Latest events preserved on memory overflow

---

## Files Modified

### Modified (5 files)
- `app.py` — Registered routes (~90 net additions)
- `config/apex_release_manifest.json` — Version bump
- `config/apex_capability_registry.yaml` — Version bump
- `scanner_worker.py` — Integrated degradation capture (~12 net additions)
- `templates/apex_os.html` — Dashboard aggregation

### Added (5 files)
- `engine/silent_degradation_observability.py` — Core module (~180 LOC)
- `engine/silent_degradation_observability_routes.py` — Flask routes (~20 LOC)
- `templates/silent_degradation_observability.html` — Dashboard view
- `tests/test_apex_67_1_silent_degradation_observability.py` — 3 test cases
- `APEX_67_1_0_SILENT_DEGRADATION_OBSERVABILITY.md` — Documentation

### Archive
- `APEX_67_1_0_Silent_Degradation_Observability_Changed_Files.zip` — Source

---

## API Responses

### `GET /api/diagnostics/degradations`

```json
{
  "ok": true,
  "status": "DEGRADED",
  "source": "SQLITE",
  "event_groups": 5,
  "occurrences": 47,
  "decision_authority_suppressed_occurrences": 12,
  "by_component": {
    "canonical_market_state": 23,
    "scanner": 24
  },
  "by_severity": {
    "DEGRADED": 47
  },
  "events": [
    {
      "fingerprint": "abc123def456789",
      "first_seen": "2026-08-17T10:00:00+00:00",
      "last_seen": "2026-08-17T12:30:00+00:00",
      "component": "scanner",
      "operation": "collect",
      "severity": "DEGRADED",
      "exception_type": "RuntimeError",
      "message": "collector state unavailable",
      "fallback": "EMPTY_COLLECTOR_STATE",
      "decision_authority_suppressed": true,
      "source": "HLCE",
      "context": { "retry_count": 3 },
      "occurrence_count": 8
    }
  ],
  "engine_version": "67.1.0",
  "schema_version": "apex.silent_degradation_observability.v1",
  "execution_authority": "NONE"
}
```

---

## Authority & Limitations

✓ **No decision authority**: Observer-only  
✓ **No execution authority**: Cannot initiate trades  
✓ **Non-mutating APIs**: Snapshot doesn't modify state  
✓ **Graceful degradation**: DB failures don't cascade  
✗ **Real-time streaming**: Uses polling (batch snapshots)  
✗ **Record mutation**: Immutable after creation  

---

## Backward Compatibility

✓ Existing database files unchanged  
✓ Existing decision logic unchanged  
✓ Existing execution paths unchanged  
✓ New routes don't conflict with existing paths  
✓ Dashboard navigation integrated non-intrusively  

---

## Observability Benefits

- **Root-cause analysis**: See exactly when fallbacks triggered
- **Pattern detection**: Fingerprints enable grouping
- **Severity tracking**: Flags decision-authority suppression
- **Historical view**: First/last seen timestamps
- **Occurrence frequency**: Count degradations over time
- **Component health**: Aggregate by component
- **Automated alerting**: API enable threshold-based alerts

---

## Summary Statistics

- **New Module LOC**: ~180 (silent_degradation_observability.py)
- **Route Module LOC**: ~20 (routes)
- **Tests**: 3 (all passing)
- **Endpoints**: 2 new (API + Dashboard)
- **Integration Points**: 6 degradation capture locations
- **Database Path**: apex_degradation_events.db

---

## Next Steps

1. ✓ Merge into `apex-66-4-1-decision-coherence`
2. Create PR for review
3. Monitor degradation events in production
4. Plan APEX 67.2.0 (future enhancements based on observability data)

---

## Related Features

- **APEX 67.0.0**: Canonical Persistence Layer (enables this feature)
- **APEX 66.9.0**: BPSPX Freshness Governance (parent feature set)
- **APEX 66.4.1**: Decision Coherence Fix (on current branch)
