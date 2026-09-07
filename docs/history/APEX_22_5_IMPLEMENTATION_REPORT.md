# APEX 22.5 — Pre-23 Hardening & Consolidation

Runtime: `15.5.0_PRE_23_HARDENING`

## Implemented

- Removed the built-in TradingView webhook secret.
- Added fail-closed webhook behavior when no secret is configured.
- Added constant-time webhook secret comparison.
- Corrected Configuration Governance registry construction order.
- Registered all environment variables identified by the pre-23 audit, including execution and risk controls.
- Added a production environment-variable drift regression test.
- Added a stable application factory and `wsgi.py` entry point.
- Added critical-route assurance and automatic route inventory.
- Added a process-scoped scanner lease to prevent duplicate scanner ownership across workers.
- Added SQLite persistence inventory and persistent-disk warnings.
- Added a deep-copied, content-addressed institutional snapshot API.
- Added Mission Control 2.0 hardening and snapshot drill-downs.
- Added a dry-run-first release-report archival utility.

## Safety

No order preview, broker mutation, automatic execution, live trading enablement, position sizing, or kill-switch behavior was added or weakened. Existing human confirmation remains authoritative.
