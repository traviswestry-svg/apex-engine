# APEX 65.7.6 — Execution Boundary Consolidation

## Scope
Closed the immediate execution-boundary loose ends before new decision-intelligence work.

## Changes
- Added a real repository `.gitignore` for runtime SQLite databases and sidecars.
- Extended `CanonicalExecutionBoundary` beyond single-leg entry to complex/multi-leg placement, order changes, and cancellation.
- Complex placements now require a registered, unexpired broker preview; the placement intent must match the previewed intent; the full complex-entry risk guard is re-run immediately before broker I/O; duplicate concurrent submission is blocked.
- Added deterministic complex-entry risk validation for SPX/SPXW, leg completeness, quote freshness, quantity, defined maximum loss, RTH/cutoff, cooldown, and live-trading gate.
- Change-order placement now requires a registered, unexpired change preview, binds the order/change intent to that preview, and re-runs line-drag risk validation at the mutation boundary.
- Cancel-order placement now crosses the canonical execution boundary and requires confirmation when configured.
- Existing single-leg canonical execution behavior remains unchanged.

## Validation
- `python -m py_compile` passed for the modified execution modules and tests.
- `tests/test_apex_65_7_integrity.py` + `tests/test_complex_options_execution.py`: 29 passed.
- `tests/test_trade_command.py`: 29 passed when run with auth tests in the same command before the auth module was collected.
- `tests/test_auth_layer.py`: 13 tests could not run because Flask is not installed in this isolated runtime (`ModuleNotFoundError: flask`). This is an environment limitation, not an observed application regression.

## Live-session follow-up
Monitor `/api/learning/evidence-readiness` and scanner heartbeat `hlce_counts`. If richer level families do not accumulate while expected-move levels do, diagnose active-level registry/session-context population rather than the HLCE collector.
