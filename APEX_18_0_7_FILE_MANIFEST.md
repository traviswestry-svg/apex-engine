# APEX 18.0.7 File Manifest

## New
- `engine/adaptive_refusal_calibration.py`
- `tests/test_adaptive_refusal_calibration_18_0_7.py`
- `APEX_18_0_7_IMPLEMENTATION_REPORT.md`
- `APEX_18_0_7_VALIDATION_REPORT.md`
- `APEX_18_0_7_DEPLOYMENT_ROLLBACK.md`
- `APEX_18_0_7_FILE_MANIFEST.md`

## Updated
- `engine/premium_discipline.py`
- `engine/premium_discipline_routes.py`
- `engine/release_manager.py`
- `app.py`

## Included from the deployed-baseline reconciliation
The uploaded repository identified itself as APEX 18.0.5 and did not contain the Trade Refusal Replay module. To preserve the requested sequence, this complete release also includes the APEX 18.0.6 replay files and tests before adding 18.0.7 calibration.
- `engine/refusal_replay.py`
- `tests/test_refusal_replay_18_0_6.py`
- APEX 18.0.6 release documentation
