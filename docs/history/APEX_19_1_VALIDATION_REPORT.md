# APEX 19.1 Validation Report

## Results
- Engine-specific tests: 14 passed
- Targeted governance, observability, health, release, broker, and execution tests: 79 passed
- Complete authoritative `tests/` regression suite: 962 passed
- Failures: 0
- Reported skips: 0

## Route smoke tests
All returned HTTP 200:
- `/api/institutional-market-structure/status`
- `/api/institutional-market-structure/diagnostics`
- `/api/institutional-market-structure/profiles`
- `/api/institutional-market-structure/levels`
- `/api/institutional-market-structure/auction`
- `/api/institutional-intelligence-engine/status`
- `/health`
- `/apex_os`

## Collection note
Running pytest against the repository root encounters a duplicate test-module name under `templates/`. The authoritative suite was run against `tests/`, after clearing bytecode caches.
