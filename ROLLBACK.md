# APEX 25.3 — ROLLBACK

25.3 is additive and shadow-only; rollback is low-risk.

## Full rollback
1. Delete the new files:
   - engine/adaptive_confidence_calibration_v253.py
   - engine/adaptive_confidence_calibration_v253_routes.py
   - tests/test_adaptive_confidence_calibration_v253.py
   - tests/test_adaptive_confidence_calibration_v253_routes.py
2. Revert `app.py` and `engine/configuration_governance.py` to their 25.2-era
   revisions (restore from version control / pre-25.3 backup).
3. Restart the app.

## Note on fail-loud registration
`app.py` registers 25.3 as required and fail-loud. Remove the engine files and
the app.py block together, or boot will raise a clear RuntimeError.

## Data
No database or schema changes were made; 25.3 only reads the existing 23.4
outcome store. Rolling back leaves all data intact.
