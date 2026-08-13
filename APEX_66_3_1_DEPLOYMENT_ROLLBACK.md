# APEX 66.3.1 Deployment / Rollback

## Deploy
1. Upload the changed files preserving repository paths, or replace the repository with the full ZIP contents.
2. Commit: `APEX 66.3.1 — Decision Adapter & State Semantics Hardening`
3. Render Build Command: `pip install -r requirements.txt`
4. Render Start Command: `./start_render.sh`
5. Normal deploy is sufficient; no cache clear or database migration is required.

## Validate
After deployment inspect `/api/institutional-decision`.

Outside RTH/weekend with no current primitive evidence, expected semantics include:
- `direction: UNKNOWN`
- `action: NO_TRADE`
- `status: MARKET_CLOSED`
- `consensus.status: UNAVAILABLE`
- all missing providers listed under `unavailable_engines`
- missing provider opinions use `ABSTAIN` + `freshness_state: UNAVAILABLE`

During RTH, existing primitive outputs should normalize from their native schemas rather than requiring a synthetic `.direction` field.

## Rollback
Revert the 66.3.1 commit and redeploy APEX 66.3.0. No database rollback is required.
