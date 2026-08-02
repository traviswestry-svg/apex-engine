# APEX 50.7.0.2 — LTPE Circular Import Repair

## Root cause
`engine.level_transition_probability` imported `engine.historical_level_calibration` at module load. HLCE also imports LTPE from collector/startup learning hooks. Under threaded Gunicorn startup/recovery this reverse dependency could expose a partially initialized LTPE module, producing:

`ImportError: cannot import name 'learning_status' from partially initialized module 'engine.level_transition_probability'`

## Repair
- Removed LTPE's eager module-load import of HLCE.
- Added a lazy HLCE proxy that resolves the shared calibration module only when LTPE executes a function requiring HLCE storage/helpers.
- Preserved the public 50.7.0 learning version for backward-compatible tests/API consumers.
- Added `CIRCULAR_IMPORT_REPAIR_VERSION = 50.7.0.2_LTPE_CIRCULAR_IMPORT_REPAIR` for repair identity.
- Kept the 50.7.0.1 JSON route fail-safe unchanged as a final containment boundary.

## Why this fixes the production failure
LTPE now completes definition of `learning_status`, `run_learning_cycle`, and the rest of its public API before it attempts to resolve HLCE. Therefore HLCE startup hooks cannot recursively request symbols from a half-defined LTPE module.

## Validation
- Production-order isolated import regression: PASS.
- Concurrent HLCE/LTPE import regression: PASS.
- Lazy HLCE resolution regression: PASS.
- Existing LTPE learning/status/fail-safe tests: PASS.
- APEX 50.x + 65.x focused regression: 67/67 PASS.
- Python compilation: PASS.

## Changed files
- `engine/level_transition_probability.py`
- `tests/test_apex_50_7_0_2_circular_import_repair.py`
- `APEX_50_7_0_2_LTPE_CIRCULAR_IMPORT_REPAIR.md`
