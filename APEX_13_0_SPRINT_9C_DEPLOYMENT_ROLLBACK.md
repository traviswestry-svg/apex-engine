# APEX 13.0 Sprint 9C Deployment and Rollback

## Deployment
Deploy the complete repository through the existing GitHub-to-Render process. Sprint 9C tables are created idempotently during route initialization.

## New tables
- institutional_releases
- release_timeline_events
- release_health_snapshots

## Rollback
Rollback the Render deployment to the prior Sprint 9B commit or deploy the Sprint 9B complete repository ZIP. The new tables are additive and can remain safely unused. Sprint 9C does not change recommendation, risk, execution, champion, or canary routing logic.
