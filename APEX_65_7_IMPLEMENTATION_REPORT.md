# APEX 65.7 — Execution & Learning Integrity

## Objective
Stabilize existing execution and learning architecture before any new feature build.

## 1. Single-owner HLCE collector
- Removed `service.start()` from `register_calibration_routes()`.
- Flask/Gunicorn route registration now has no collector lifecycle side effect.
- `scanner_worker.py` explicitly owns HLCE startup.
- Existing `CalibrationService.start()` idempotency remains as a second line of defense inside the scanner process.

## 2. Canonical execution boundary
Added `engine/execution/canonical_execution.py`.

`/api/trade/spx/place-entry` can no longer call the broker adapter directly. Placement now requires:
- a known broker preview id registered by APEX;
- an unexpired preview (`APEX_EXECUTION_PREVIEW_TTL_SECONDS`, default 30s);
- single-use preview consumption/idempotency;
- full `trade_risk_guard.validate_entry()` re-validation immediately before broker I/O;
- current session state, quantity, entry/stop risk, quote freshness/spread, cooldown, and live-trading gate validation.

`_LAST_ORDER_EPOCH` is updated only after a successful placement.

## 3. Learning readiness contract
Added `engine/learning_maturity.py` with a shared maturity schema:
- `UNINITIALIZED`
- `EARLY_SAMPLE`
- `STATISTICALLY_USABLE`
- `DEGRADED`

LTPE zone probabilities and institutional-governance history now return `maturity`, `statistically_usable`, minimum/sample counts, and a display policy. Evidence values may remain available for audit/research, but thin-sample values are explicitly forbidden from being rendered as calibrated confidence.

## 4. Persistence hygiene
- Runtime root database files are removed from the release artifact.
- `.gitignore` now excludes SQLite runtime databases and WAL/SHM files.
- Production persistence remains expected on `/data` through the existing path-resolution configuration.

## 5. Influence visibility
Operations endpoint inventory now includes:
- `influence_class`
- `influences_decision`
- `can_reach_execution`

Classes distinguish `DECISION_CORE`, `RISK_GATE`, `EXECUTION_GATE`, `LEARNING_PRODUCER`, `ADVISORY`, `SHADOW`, `DIAGNOSTIC`, and `DEPRECATED` so route existence no longer implies decision authority.

## Validation
New APEX 65.7 tests cover:
- placement-time risk re-validation before adapter I/O;
- duplicate preview/order submission blocking;
- thin-sample learning maturity gating;
- no HLCE collector startup from route registration;
- scanner ownership of HLCE startup;
- runtime DB ignore policy.

Environment note: broader auth tests require Flask in the validation environment. In this container those auth tests fail at import with `ModuleNotFoundError: flask`; this is dependency/environmental and unrelated to the APEX 65.7 changes. Non-Flask targeted suites executed successfully.
