# APEX Scanner–Learning Workload Continuity Closure — safe candidate

Baseline: October 19, 2026 repository. Version remains 69.10.37.

## Scope
- Adds a pure, testable single-owner learning-admission decision.
- Separates DISABLED, UNAVAILABLE, UNWIRED, SESSION_GATED and DEFERRED_SCANNER_DEADLINE reasons.
- Publishes consecutive deadline deferrals, starvation warning, work estimate, and remaining budget via existing scanner flow-learning runtime telemetry.
- Preserves scan priority, serial SQLite writer ownership, exact canonical sample IDs, and execution_authority=false.

## Important limitation
This candidate **detects and explains** learning starvation but **does not eliminate it**. The current 120-second monolithic flow-learning pipeline cannot safely be admitted under the 180-second scan freshness deadline when scan work consumes most of the budget. Eliminating starvation requires splitting the flow pipeline into bounded resumable units with transaction-safe checkpoints or a separately coordinated writer, and is NOT implemented here. Do not treat this as a complete learning continuity fix.

## Validation
Run focused tests and full CI on the matching repository. Verify during RTH that scanner freshness stays under 180 seconds and monitor `flow_learning_runtime.learning_starvation_warning`; a warning means learning is still not progressing.
