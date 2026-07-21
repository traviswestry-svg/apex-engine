# APEX DB Resilience Hotfix — VALIDATION

Executed in-container:
- `python3 -m py_compile` clean for engine/db_resilience.py, signal_evaluator.py, app.py.
- Hotfix tests: **8 passed** (corrupt-file quarantine, valid-file untouched,
  data preserved not deleted, idempotent heal, and signal_evaluator scorecard /
  mark_due / record_signal on a fresh AND on a corrupt DB — no 'no such table',
  no 'file is not a database').
- Full repository suite after integration: **1299 passed, 1 deselected**
  (the deselected test is the pre-existing timing-sensitive refusal_replay case,
  unrelated to this hotfix). Zero new failures.
- App still imports; route count unchanged (702 on the full stack; unaffected on 25.4).
- Env-drift governance guard passes (no new env vars introduced).

## What this fixes at runtime
- A corrupt `/data/apex_tracking.db` is quarantined on first use and rebuilt,
  instead of bricking tracking and the evaluator.
- `pine_signals` is created on first read/write regardless of startup ordering,
  so the scanner can never hit 'no such table' again.
- Once signals log and outcomes score, 25.3 calibration and 25.4 review finally
  have data to work with.
