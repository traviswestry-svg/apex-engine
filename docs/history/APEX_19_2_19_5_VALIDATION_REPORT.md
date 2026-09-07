# APEX 19.2–19.5 Validation Report

## Targeted validation
- Intelligence-engine focused tests: 23 passed
- Expanded governance, observability, health, release, broker, confirmation, sandbox, and execution suite: 95 passed

## Full regression
- 971 passed
- 0 failed
- 0 reported skips

## Route smoke validation
The following routes returned HTTP 200:
- `/api/dealer-positioning/status`
- `/api/dealer-positioning/diagnostics`
- `/api/options-flow-intelligence/status`
- `/api/options-flow-intelligence/diagnostics`
- `/api/institutional-probability/status`
- `/api/institutional-probability/diagnostics`
- `/api/adaptive-learning-v2/status`
- `/api/adaptive-learning-v2/diagnostics`
- `/api/institutional-market-structure/status`
- `/api/institutional-intelligence-engine/status`
- `/health`
- `/apex_os`

## Safety validation
- Broker mutation remains disabled in all new engines.
- No live or automatic trading was enabled.
- Adaptive weights are suggestions only and require human approval.
- `NOT_EXECUTABLE` recommendations are excluded from learning history.
- Stale-data warnings remain explicit.
