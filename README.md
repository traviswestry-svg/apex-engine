# APEX Signal Integrity & Runtime Resilience — candidate patch

Source baseline: uploaded `apex-engine-main.zip` (October 14 repository snapshot).

## Changed files
- `app.py`: guard missing/nonfinite stop, target, entry, and price values during OPEN signal updates; record abstentions rather than allowing float/None comparisons; log institutional volume-profile wall-clock duration and timeout status.
- `engine/signal_integrity_guard.py`: pure numeric validation and direction-aware stop/target classifier.
- `tests/test_signal_integrity_guard.py`: focused regression tests.

## Validation
- `python -m pytest -q tests/test_signal_integrity_guard.py` — 4 passed.
- `python -m py_compile app.py engine/signal_integrity_guard.py` — passed.
- Full repository CI, Render production validation, and load/timeout profiling **not run**.

## Boundaries
- No release version bump, database migration, broker execution, scheduler or settlement change.
- A timed-out volume-profile Future may continue running in its executor thread; this patch **instruments** but does not solve background thread accumulation or root-cause the 3-second timeout.
- Existing EXPIRED session/hold policy remains unchanged when a valid entry and exit price exist. Missing prices do not create synthetic outcomes.
- Apply to development branch and run full CI before production promotion.
