# APEX 20.0 Validation Report

## Automated testing
- Decision engine and underlying intelligence tests: 30 passed
- Targeted governance, observability, health, release, confirmation, and complex-options tests: 69 passed
- Complete authoritative `tests/` regression suite: 978 passed
- Failures: 0
- Reported skips: 0

## Route smoke validation
HTTP 200 verified for:
- `/api/institutional-decision/status`
- `/api/institutional-decision/diagnostics`
- `/api/institutional-decision/scenarios`
- `/api/institutional-decision/evidence`
- `/api/institutional-decision/strategy`
- `/health`
- `/apex_os`

## Additional checks
- Python compilation passed for new engine, routes, and modified application registration.
- Secret-like input fields are not copied into output.
- Stale input fails closed.
- Empty input returns STAND_DOWN.
- Strategy selection remains advisory only.
- Full regression rerun after route endpoint collision correction passed.
