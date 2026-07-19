# APEX 18.0.8 Deployment and Rollback

## Deployment

1. Deploy the complete APEX 18.0.8 repository.
2. Confirm `/api/system/version` reports `11.0.6_PREMIUM_DISCIPLINE_COMMAND_CENTER`.
3. Open `/apex_os/premium_discipline`.
4. Confirm `/api/premium_discipline/command-center` returns HTTP 200.
5. Verify the page states that it is advisory only and has no execution authority.
6. Run calibration only after replay outcomes have accumulated; promote only after reviewing the evidence.

## Rollback

Redeploy the prior complete APEX 18.0.7 repository. APEX 18.0.8 adds no destructive database migration. Existing premium-discipline, replay, and calibration data remain compatible with the prior release.
