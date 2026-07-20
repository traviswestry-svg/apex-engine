# APEX 25.2 — ROLLBACK

25.2 is additive and shadow-only. Rollback is low-risk.

## Full rollback
1. Delete the new files:
   - engine/decision_outcome_forecast_v252.py
   - engine/decision_outcome_forecast_v252_routes.py
   - tests/test_decision_outcome_forecast_v252.py
   - tests/test_decision_outcome_forecast_v252_routes.py
2. Revert `app.py` and `engine/configuration_governance.py` to their prior
   revisions (restore from version control or the pre-25.2 backup).
3. Restart the app.

## Note on the fail-loud registration
`app.py` registers 25.2 as required and fail-loud (matching 25.0/25.1). If you
remove the engine files but NOT the app.py block, boot will raise a clear
RuntimeError. Always revert `app.py` together with the engine files.

## Data
The sqlite store `apex_decision_forecast.db` is standalone; deleting the file
removes all shadow forecasts and has no effect on any other APEX data.
No schema migration was applied to any shared database.
