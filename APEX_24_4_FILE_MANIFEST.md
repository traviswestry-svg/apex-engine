# APEX 24.4 Changed File Manifest

## Added
- `engine/institutional_multi_timeframe_v244.py`
- `engine/institutional_multi_timeframe_v244_routes.py`
- `tests/test_institutional_multi_timeframe_v244.py`
- `APEX_24_4_IMPLEMENTATION_REPORT.md`
- `APEX_24_4_VALIDATION_REPORT.md`
- `APEX_24_4_FILE_MANIFEST.md`
- `APEX_24_4_DEPLOYMENT_ROLLBACK.md`
- `APEX_24_4_API_STABILITY_INVENTORY.md`

## Modified
- `app.py` — 24.4 import guard (with verifier) + dedicated fail-loud registration.
- `engine/institutional_mission_control_v213.py` — `MULTI_TIMEFRAME` panel +
  drill-down.
- `engine/release_manager.py` — release identity bumped to
  `17.4.0_MULTI_TIMEFRAME_INTELLIGENCE`.
