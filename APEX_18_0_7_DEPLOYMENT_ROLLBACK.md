# APEX 18.0.7 Deployment and Rollback

## Deployment

1. Deploy the complete APEX 18.0.7 repository.
2. Confirm `/api/system/version` reports `11.0.5_ADAPTIVE_REFUSAL_CALIBRATION`.
3. Confirm the calibration endpoint returns an active default or promoted policy.
4. Run calibration only after sufficient replay outcomes exist.
5. Review a recommendation before explicitly promoting it.

## Rollback

Redeploy the prior APEX 18.0.6 complete repository. The calibration tables may remain in SQLite; prior versions ignore them. No destructive database rollback is required.
