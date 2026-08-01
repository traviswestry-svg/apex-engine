# APEX 50.6.2.1 — LTPE Context Resolver Fail-Safe Repair

## Objective
Repair the production `/api/level-calibration/transitions/path` HTML 500 introduced after 50.6.2 canonical-context deployment without changing LTPE probability policy or trading/execution logic.

## Findings
The 50.6.2 path calculation reproduces successfully against the archived next-session Morning Brief payload, indicating the deployed failure is environment/persistence-state dependent rather than a deterministic path arithmetic defect. The read-only endpoint previously allowed persistence/schema/statistics exceptions to escape Flask and render the generic HTML Internal Server Error page.

## Changes
- Bumped LTPE component version to `50.6.2.1_LEVEL_TRANSITION_PROBABILITY`.
- Made persisted HLCE spot and level fallback reads fail-soft for stale/missing schema or database errors.
- Added staged structured failures for store initialization, context extraction, level-universe resolution, spot resolution, and path assembly.
- Made transition-statistics lookup fail independently: the structural path remains available and probability stays null with `STATISTICS_UNAVAILABLE`.
- Added final HTTP route boundary so `/transitions/path` always returns JSON diagnostics rather than Flask HTML 500.
- Preserved evidence-only probability policy and read-only fallback semantics.

## Validation
- Targeted HLCE/LTPE/APEX 65 regression suite: 76/76 PASS.
- Repository-wide Python compilation: PASS.
- Failure injection covers persistence failure, statistics failure, and unexpected level resolver exception.

## Behavioral Contract
No trading, risk, broker, order, signal, or historical probability calculation behavior was changed. No fallback context is written into LTPE observations.
