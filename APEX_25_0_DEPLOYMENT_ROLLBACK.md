# APEX 25.0 Deployment and Rollback

## Deployment

Deploy through the existing GitHub-to-Render workflow. No new environment variables or database migrations are required.

After deployment, verify:

1. `/api/system/version` reports `25.0.0_INSTITUTIONAL_DECISION_INTEGRITY`.
2. `/api/decision-integrity/status` returns `READY`.
3. `/api/decision-integrity/current` returns a decision record.
4. Mission Control includes `DECISION_INTEGRITY`.

## Rollback

Rollback to the previous Render deployment or revert the files in the 25.0 manifest. APEX 25.0 creates no tables and performs no persistent-state mutation, so rollback requires no data migration.
