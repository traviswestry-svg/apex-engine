# APEX 66.9.0 — BPSPX Freshness Governance Merge Summary

**Date**: 2026-08-17  
**Branch**: apex-66-4-1-decision-coherence  
**Source**: APEX_66_9_0_BPSPX_Freshness_Governance_Changed_Files.zip

---

## Overview

This merge integrates fail-closed observation-age governance into the Breadth Regime, ensuring that stale BPSPX observations cannot influence horizon-specific trading decisions. The implementation adds timestamp-based freshness validation with configurable session-aware thresholds.

---

## Key Changes

### 1. Core Implementation (`engine/breadth_regime.py`)

**Version**: 66.5.0 → 66.9.0  
**Schema**: v1 → v2

#### New Functions
- **`_parse_timestamp()`**: Robust ISO 8601 timestamp parsing with UTC normalization
- **`_freshness_governance()`**: Central freshness validation logic

#### New Constants
- `DEFAULT_CURRENT_MAX_AGE_MINUTES = 1440` (24 hours)
- `DEFAULT_PRIOR_SETTLED_MAX_AGE_MINUTES = 5760` (4 days)
- `FRESHNESS_VERSION = "apex.bpspx_freshness.v1"`

#### Modified Signature
```python
def build_breadth_regime(
    context: Optional[Mapping[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
    current_max_age_minutes: int = DEFAULT_CURRENT_MAX_AGE_MINUTES,
    prior_settled_max_age_minutes: int = DEFAULT_PRIOR_SETTLED_MAX_AGE_MINUTES,
) -> dict[str, Any]:
```

#### Freshness States
| State | Condition | Usable | Horizon Weight |
|-------|-----------|--------|---|
| `CURRENT_SESSION` | Fresh observation during market hours | ✓ Yes | Normal |
| `PRIOR_SETTLED_SESSION` | Recent observation during market closure | ✓ Yes | Normal |
| `STALE` | Observation exceeds max age | ✗ No | 0.0 |
| `DATA_LIMITED` | Missing/invalid timestamp | ✗ No | 0.0 |

---

### 2. Configuration Updates

#### `config/apex_release_manifest.json`
- **Version**: 66.8.0 → 66.9.0
- **Build Name**: Confidence Calibration Audit

#### `config/apex_capability_registry.yaml`
- **Schema Version**: apex.capability_registry.v1
- **APEX Version**: 66.8.0 → 66.9.0
- Breadth Regime capability remains at v66.5.0 in registry (implementation is v66.9.0)

---

### 3. Test Coverage

#### New Test Suite: `tests/test_breadth_regime_freshness.py`
6 comprehensive test cases:
1. Missing timestamp defaults to DATA_LIMITED
2. Current session observation is usable
3. Stale open-session observation suppresses influence
4. Prior settled observation allowed when market closed
5. Old weekend carry-forward becomes stale
6. Invalid timestamp triggers DATA_LIMITED

#### Updated Existing Tests: `tests/test_breadth_regime.py`
- Added `NOW` fixture (2026-08-17 12:00 UTC)
- Updated all tests to provide `bpspx_observed_at` timestamp
- Passed `now` parameter to `build_breadth_regime()` for time control
- **All 11 breadth regime tests passing** ✓

---

### 4. Documentation

**New File**: `APEX_66_9_0_BPSPX_FRESHNESS_GOVERNANCE.md`

Defines:
- Four freshness governance states
- Authority guarantees (fail-closed, no execution authority)
- Codespace compatibility notes

---

## Behavioral Impact

### Before (66.5.0)
- BPSPX observations used immediately regardless of age
- No timestamp validation
- Risk of stale data influencing decisions

### After (66.9.0)
- **Fail-closed**: Missing/invalid timestamp → DATA_LIMITED → zero horizon weight
- **Session-aware**: Different thresholds for open vs. closed market
- **Configurable**: Callers can adjust max age parameters
- **Traceable**: Freshness metadata included in response

### Example Responses

**Stale Observation (Open Market)**:
```json
{
  "status": "DATA_LIMITED",
  "state": "DATA_LIMITED",
  "bpspx": 42.0,
  "freshness": {
    "state": "STALE",
    "usable": false,
    "reason": "bpspx_observation_too_old",
    "age_minutes": 1500
  },
  "horizon_influence": {
    "SCALP": {"weight": 0.0, "effect": "DATA_LIMITED"},
    "INTRADAY": {"weight": 0.0, "effect": "DATA_LIMITED"},
    "SWING": {"weight": 0.0, "effect": "DATA_LIMITED"}
  }
}
```

**Fresh Observation (Open Market)**:
```json
{
  "status": "READY",
  "state": "CONFIRMED_RECOVERY",
  "bpspx": 32.0,
  "freshness": {
    "state": "CURRENT_SESSION",
    "usable": true,
    "age_minutes": 30
  },
  "horizon_influence": {
    "SCALP": {"weight": 0.10},
    "INTRADAY": {"weight": 0.35},
    "SWING": {"weight": 0.85}
  }
}
```

---

## Files Modified/Added

### Modified
- `engine/breadth_regime.py` (176 line diff)
- `config/apex_release_manifest.json` (version bump)
- `config/apex_capability_registry.yaml` (version bump)
- `tests/test_breadth_regime.py` (timestamps & now param added)

### Added
- `tests/test_breadth_regime_freshness.py` (new test suite)
- `APEX_66_9_0_BPSPX_FRESHNESS_GOVERNANCE.md` (documentation)
- `APEX_66_9_0_BPSPX_Freshness_Governance_Changed_Files.zip` (source archive)
- `_check/` directory (staging/reference files)

### Deleted
- `APEX_66_7_0_DYNAMIC_STATE.zip` (superseded)

---

## Testing Results

```
✓ test_breadth_regime.py::test_missing_bpspx_fails_closed_without_direction
✓ test_breadth_regime.py::test_sub_15_falling_is_capitulation_not_buy_signal
✓ test_breadth_regime.py::test_rising_from_extreme_is_early_not_confirmed_recovery
✓ test_breadth_regime.py::test_cross_above_30_confirms_recovery
✓ test_breadth_regime.py::test_routes_expose_dashboard_payload
✓ test_breadth_regime_freshness.py::test_missing_timestamp_fails_closed_even_with_value
✓ test_breadth_regime_freshness.py::test_current_session_observation_is_usable
✓ test_breadth_regime_freshness.py::test_stale_open_session_observation_suppresses_influence
✓ test_breadth_regime_freshness.py::test_prior_settled_session_allowed_when_market_closed
✓ test_breadth_regime_freshness.py::test_old_weekend_carry_forward_becomes_stale
✓ test_breadth_regime_freshness.py::test_invalid_timestamp_is_data_limited

11 passed in 1.37s
```

---

## Compatibility Notes

- **Backward Compatible**: Observations without timestamps default to fail-closed
- **API Contract**: No breaking changes to existing routes
- **Database**: No schema changes required
- **Codespaces**: No absolute paths or Render-specific assumptions introduced

---

## Next Steps

Ready for commit to `apex-66-4-1-decision-coherence` branch.
