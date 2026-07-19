# APEX 18.0.5 Deployment and Rollback

## Deployment
1. Back up the current APEX 18.0.4 deployment.
2. Deploy the complete APEX 18.0.5 repository package.
3. Optionally set `PREMIUM_ELIGIBILITY_THRESHOLD`; default is `65`.
4. Confirm `/api/system/version` reports `11.0.3_PREMIUM_DISCIPLINE`.
5. Confirm the three `/api/premium_discipline*` endpoints return HTTP 200.

## Rollback
Redeploy the prior APEX 18.0.4 complete repository. The added `premium_discipline_decisions` table may remain; prior versions ignore it. No destructive schema rollback is required.
