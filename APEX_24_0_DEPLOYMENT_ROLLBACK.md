# APEX 24.0 Deployment and Rollback

## Deployment

Deploy the complete repository using the existing Render build and start commands. No environment-variable change is required.

The new SQLite tables are created automatically in `DB_PATH`:

- `apex_execution_lifecycles_v240`
- `apex_execution_events_v240`

For durable journals, ensure `DB_PATH` is on the configured Render persistent disk.

## Rollback

Redeploy the previous APEX 23.5 release. The two APEX 24.0 tables may remain in the database; older code does not reference them. No destructive rollback migration is required.
