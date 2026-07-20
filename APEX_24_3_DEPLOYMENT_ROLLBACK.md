# APEX 24.3 Deployment and Rollback

## Deployment

Deploy the complete repository using the existing Render build and start
commands. No environment-variable change is required.

New SQLite tables (created automatically in the governance DB):
- `apex_research_experiments_v243`
- `apex_research_experiment_versions_v243`

### Startup behaviour

The Strategy Research Laboratory surface is required. If its module cannot
import, or any canonical route cannot register, startup raises `RuntimeError`.

## Rollback

Redeploy the previous APEX 24.2 release. The two APEX 24.3 tables may remain in
the database; older code does not reference them. After rollback the legacy
`/api/research/status` route (findings + similarity) is restored automatically
with the older code. No destructive rollback migration is required.
