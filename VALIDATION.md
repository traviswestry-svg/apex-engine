# APEX 26.6-26.10 — VALIDATION

All results below were produced by executing the commands in this container.

## Python compilation
`python3 -m py_compile` succeeded for all new/modified files.

## Test suite (actually executed)
- Part-2 module: **20 passed** (26.6-26.10 engines + routes; file holds 26 test
  functions, some grouped).
- Complete repository suite: **1291 passed, 1 deselected**.
  * The deselected test is the pre-existing, timing-sensitive
    `tests/test_refusal_replay_18_0_6.py::test_due_replay_is_idempotent_and_persists_scorecard`
    (fails identically on the untouched original repo). This suite introduced
    ZERO new failures.
  * Note: an earlier draft of 26.7 referenced a non-existent env var; the
    repository's env-drift governance guard caught it and it was fixed to use the
    real registered switches (ETRADE_ENABLE_TRADING +
    APEX_CONFIRMATION_GATED_EXECUTION_ENABLED). The guard now passes.

## Application import
- `import app` succeeds; no duplicate scanner start.
- Route map grew 691 -> 702 (+11 routes). verify_registered returns no missing
  routes; registration is fail-loud.
- Live smoke: trade-story/broker/command-center/trader-mode current all 200.

## Routes registered (11, all advisory)
- /api/trade-story/{status,current,evaluate}
- /api/broker-intelligence/{status,current,preview}   (preview/read-only)
- /api/execution-review/{status,evaluate}
- /api/command-center/{status,current}
- /api/trader-mode/current

## Safety verified
- places_orders / submits_orders False; production_effect NONE everywhere.
- 26.7 exposes no order-submission function (asserted in test) and reports the
  real execution gate rather than bypassing it.
- 26.9/26.10 aggregators never crash on empty input (asserted).

## Database / environment changes
- None. No new env vars; no new database.
