# APEX 23.2 Deployment and Rollback

## Deployment

Deploy the complete repository through the existing GitHub/Render workflow. No database migration or new required environment variable is introduced.

## Verification

Confirm HTTP 200 for `/health` and `/api/institutional-forecast/status`. During closed or sparse-data sessions, `status: LIMITED` is expected and is not a deployment failure.

## Rollback

Redeploy the previously verified APEX 23.1 commit or repository package. A rollback does not require database restoration because APEX 23.2 adds no schema changes or persistent writes.
