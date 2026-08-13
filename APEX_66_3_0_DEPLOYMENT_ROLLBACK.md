# APEX 66.3.0 Deployment & Rollback

## Deploy
1. Commit the changed files to the existing GitHub `main` branch.
2. Delete every path listed in `APEX_66_3_0_DELETE_FILES.txt` from GitHub. The changed-files ZIP cannot itself remove files when using GitHub's browser uploader.
3. Commit message: `APEX 66.3.0 — Decision Reasoning Consolidation Foundation`.
4. Render build command remains: `pip install -r requirements.txt`.
5. Render start command remains: `./start_render.sh`.
6. Use a normal deploy. No build-cache clear is required by this release.

## Post-deploy validation
Verify:
- `/api/system/version` reports 66.3.0.
- `/api/institutional-decision` returns `schema_version=apex.institutional_decision.v3` and `authoritative_contract=true`.
- `/api/institutional-consensus` exposes correlation-aware fields and configured decorrelation provenance.
- `/api/institutional-conviction` exposes `raw_conviction`, `calibrated_conviction`, and `calibration_state`.
- Legacy `/api/institutional-decision/diagnostics` reports `compatibility_adapter=true` and `authoritative_decision_source=engine.institutional_decision_object`.
- Runtime route audit remains healthy.
- Execution-boundary and HLCE health endpoints remain unchanged/healthy.

## Rollback
Revert the 66.3.0 Git commit and redeploy APEX 66.2.2. Restore the removed files automatically by reverting the commit; do not reconstruct them manually.

No database downgrade or data rollback is required because 66.3.0 has no schema migration and does not rewrite historical evidence.
