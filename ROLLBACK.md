# APEX DB Resilience Hotfix — ROLLBACK

Low-risk; additive and defensive.

1. Delete engine/db_resilience.py and tests/test_db_resilience.py.
2. Revert signal_evaluator.py to the prior version (removes _ensure_ready and the
   heal import; the readers go back to their original behavior).
3. Revert the app.py snippet if applied.
4. Restart.

## Note
Quarantined files named `*.corrupt-*.bak` are safe to keep or delete; they are
the unreadable originals the heal moved aside and contain no recoverable SQLite
data. Rolling back does not re-corrupt anything.
