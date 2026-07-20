# APEX 26.0 — ROLLBACK

26.0 is additive and advisory-only; rollback is low-risk.

## Full rollback
1. Delete the new files:
   - engine/execution_intelligence_core_v260.py
   - engine/execution_intelligence_core_v260_routes.py
   - tests/test_execution_intelligence_core_v260.py
   - tests/test_execution_intelligence_core_v260_routes.py
2. Revert `app.py` to its 25.5-era revision.
3. Restart the app.

## Note on fail-loud registration
`app.py` registers 26.0 as required and fail-loud. Remove the engine files and
the app.py block together, or boot will raise a clear RuntimeError.

## Data
No database or schema changes were made; nothing to clean up. Existing execution
and risk-guard behavior is untouched by 26.0.
