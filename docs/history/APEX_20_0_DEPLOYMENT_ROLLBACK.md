# APEX 20.0 Deployment and Rollback

## Deployment
1. Back up the current Render deployment and environment settings.
2. Deploy the complete APEX 20.0 repository.
3. Confirm runtime identity reports `13.0.0_INSTITUTIONAL_DECISION_ENGINE`.
4. Verify `/health`, `/apex_os`, and all `/api/institutional-decision/*` routes return HTTP 200.
5. Confirm Mission Control displays the Institutional Decision Engine panel.
6. Leave automatic execution and live broker mutation unchanged and disabled unless already intentionally governed.
7. Validate during a market session that evidence coverage and stale-data gates behave as expected before relying on decision output.

## Rollback
No database migration is included. Rollback is code-only:
1. Redeploy the previously validated APEX 19.2–19.5 complete repository.
2. Verify the prior runtime version and `/health` response.
3. Confirm Trade Command Center and broker safeguards remain unchanged.

## Fail-closed behavior
When evidence is missing, stale, neutral, or low-confidence, the engine returns WATCH or STAND_DOWN and marks execution ineligible. It does not alter broker permissions.
