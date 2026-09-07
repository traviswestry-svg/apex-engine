# APEX 24.3 Changed File Manifest

## Added
- `engine/institutional_research_lab_v243.py`
- `engine/institutional_research_lab_v243_routes.py`
- `tests/test_institutional_research_lab_v243.py`
- `tests/test_institutional_research_lab_v243_routes.py`
- `APEX_24_3_IMPLEMENTATION_REPORT.md`
- `APEX_24_3_VALIDATION_REPORT.md`
- `APEX_24_3_FILE_MANIFEST.md`
- `APEX_24_3_DEPLOYMENT_ROLLBACK.md`
- `APEX_24_3_API_STABILITY_INVENTORY.md`

## Modified
- `app.py` — 24.3 import guard (with verifier); dedicated fail-loud registration
  block with a legacy status provider preserving the pre-24.3
  `/api/research/status` payload.
- `engine/institutional_roadmap_routes.py` — removed the legacy
  `/api/research/status` route (24.3 now canonical; payload preserved via
  provider). All other research routes untouched.
- `engine/institutional_mission_control_v213.py` — `STRATEGY_RESEARCH` panel +
  drill-down.
- `engine/release_manager.py` — release identity bumped to
  `17.3.0_STRATEGY_RESEARCH_LABORATORY`.
