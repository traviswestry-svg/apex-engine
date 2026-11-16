# APEX Flow Learning Starvation & Scanner Deadline Scheduling Audit

## Build scope
Base: `apex-engine-main(20261112-221036).zip`, APEX version 69.10.47.
Incremental read-only runtime diagnostic; no scheduler parameter, deadline admission, flow writer, or broker change.

## Confirmed source finding
The scanner in `app.py` invokes `assess_learning()` after completing a full scan. The existing policy allocates:

`completion_budget = HEALTH_STALE_AFTER_S - elapsed_cycle_seconds - estimated_next_scan_seconds - APEX_POST_SCAN_RESERVE_SECONDS`

Default values: 180 seconds stale threshold, 45 seconds post-scan reserve, 120 seconds optional-learning estimate. With a 33.0-second estimated scan the theoretical maximum available budget is **102 seconds**, even at zero elapsed-cycle time. Thus the configured optional work cannot be admitted under these assumptions, regardless of how many deferrals have accumulated. The November 16 snapshot records 75 consecutive deadline deferrals, last estimate 120.0 and budget 30.032 seconds. This is a policy arithmetic mismatch, not proof of actual pipeline runtime.

## New behavior
`engine/flow_learning_deadline_audit.py` computes a bounded numeric explanation for every scanner-owned admission assessment, stored in `_FLOW_LEARNING_RUNTIME['deadline_audit']`. Reports gate status, input estimates, theoretical maximum, actual remaining budget, shortfall, and structural-vs-transient classification. It never influences `_learning_admission` or scanner sleeping. The diagnostic piggybacks on existing scanner heartbeat publishing. The existing full scanner remains the sole owner of learning admission.

## Key classifications
- `STRUCTURALLY_INFEASIBLE_AT_CURRENT_ESTIMATE`: estimated learning work exceeds maximum budget even with elapsed=0.
- `TRANSIENT_DEADLINE_DEFERRAL`: learning could fit in principle but did not fit this cycle.
- `UPSTREAM_GATE_BLOCKED`: feature disabled, unavailable, unwired, or outside permitted session.
- `ADMITTED`: unchanged policy admitted the optional work.

## Validation
- 16 deadline/continuity and new-audit tests passed.
- 54 scanner/scheduler/flow targeted tests passed (includes above 16).
- 24 release truth, consolidation, gamma, and canonical settlement tests passed.
- Total distinct selected tests: 78; full CI not certified.
- Python compilation passed; no changes to feature identity, settlement, broker preflight, or execution authority.

## Recommended follow-up (not implemented)
A future change to estimated learning work or scheduling strategy requires measured pipeline runtime and strict scanner-freshness regression testing. Do **not** simply lower the 120-second estimate to force work through; a non-preemptible workload may violate scanner freshness. Consider an independent bounded work scheduling design only after verifying ownership and persistence rules. No asynchronous writer is introduced here.

## Deployment
Apply `app.py.patch` with `git apply` from repo root and add `engine/flow_learning_deadline_audit.py` and `tests/test_flow_learning_deadline_audit.py`. Run repository CI. Check `/health` scanner heartbeat `flow_learning_runtime.deadline_audit` once scanner has completed a cycle. A read-only schema change may require ensuring heartbeat compacting retains the new scalar object; no existing telemetry was removed.
