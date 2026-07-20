# APEX 24.4 Deployment and Rollback

## Deployment

Deploy the complete repository using the existing Render build and start
commands. No environment-variable change and no database change is required
(the engine is stateless).

To feed real timeframe trends, populate `last['multi_timeframe']` (or
`timeframe_trends`) with per-timeframe `{trend, strength}` entries in the
scanner; absent that, the engine returns a NEUTRAL, no-data view.

### Startup behaviour

The Multi-Timeframe surface is required. If its module cannot import, or any
canonical route cannot register, startup raises `RuntimeError`.

## Rollback

Redeploy the previous APEX 24.3 release. No database artifacts are created by
24.4, so rollback is clean.
