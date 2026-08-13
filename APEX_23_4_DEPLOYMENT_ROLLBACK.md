# APEX 23.4 Deployment and Rollback

## Deploy

Deploy the complete repository normally. No new environment variable is required. The engine uses the existing governed `DB_PATH` store and creates two additive tables idempotently.

## Rollback

Redeploy the prior APEX 23.3 repository. The additive `apex_learning_outcomes_v234` and `apex_learning_recommendations_v234` tables may remain; APEX 23.3 does not reference them.

## Safety

Do not expose the outcome-recording endpoint to untrusted callers. It records learning labels only and cannot place trades, but its data affects advisory calibration reports.
