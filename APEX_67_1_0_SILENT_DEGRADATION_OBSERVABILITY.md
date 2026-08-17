# APEX 67.1.0 — Silent-Degradation Observability

Adds durable, structured visibility for non-fatal fallbacks and swallowed exceptions.

## Captured fields
- component and operation
- exception type and bounded message
- fallback actually used
- first/last seen timestamps
- recurrence count
- source
- optional context
- whether decision authority was suppressed

## Safety
The recorder is best-effort. It falls back to an in-memory ring if its SQLite
store is unavailable and never raises into the calling component. It has no
decision or execution authority.

## Initial instrumentation
- canonical market state composition
- flow tape and market-driver provider fallbacks
- execution-governance canonical decision provider
- Active Trade Director input providers
- Range Intelligence providers
- HLCE scanner collector-state fallback

Dashboard: `/apex_os/degradations`
API: `/api/diagnostics/degradations`
