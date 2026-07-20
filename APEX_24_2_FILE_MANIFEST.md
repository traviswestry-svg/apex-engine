# APEX 24.2 Changed File Manifest

## Added
- `engine/institutional_replay_v242.py`
- `engine/institutional_replay_v242_routes.py`
- `tests/test_institutional_replay_v242.py`
- `tests/test_institutional_replay_v242_routes.py`
- `APEX_24_2_IMPLEMENTATION_REPORT.md`
- `APEX_24_2_VALIDATION_REPORT.md`
- `APEX_24_2_FILE_MANIFEST.md`
- `APEX_24_2_DEPLOYMENT_ROLLBACK.md`
- `APEX_24_2_API_STABILITY_INVENTORY.md`

## Modified
- `app.py` — 24.2 import guard (with verifier); demoted the legacy
  `/api/replay/session` route to a reusable helper; added a dedicated fail-loud
  24.2 registration block (passes `legacy_session_provider`).
- `engine/institutional_mission_control_v213.py` — `REPLAY_SIMULATOR` panel +
  drill-down.
- `engine/release_manager.py` — release identity bumped to
  `17.2.0_INSTITUTIONAL_REPLAY_SIMULATOR`.
