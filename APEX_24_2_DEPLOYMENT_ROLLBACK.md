# APEX 24.2 Deployment and Rollback

## Deployment

Deploy the complete repository using the existing Render build and start
commands. No environment-variable change is required.

New SQLite tables (created automatically in the governance DB):
- `apex_replay_sessions_v242`
- `apex_replay_events_v242`

For durable replay history, ensure the governance DB path is on the configured
Render persistent disk.

### Startup behaviour

The Replay & Simulator surface is required. If its module cannot import, or any
canonical route cannot register (including duplicate-route conflicts), startup
raises `RuntimeError` and fails loudly.

## Rollback

Redeploy the previous APEX 24.1 release. The two APEX 24.2 tables may remain in
the database; older code does not reference them. After rollback the legacy
`/api/replay/session` route decorator is restored automatically with the older
code. No destructive rollback migration is required.
