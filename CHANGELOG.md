# APEX DB Resilience Hotfix (CHANGELOG)

Fixes the two production faults in the deploy log: 'file is not a database'
(corrupt tracking DB) and 'no such table: pine_signals' (evaluator read before
init). Safe to apply on the currently deployed build (25.4) — it does not touch
route registration and adds no engine dependencies.

## Root cause
- A live `apex_tracking.db` was committed to the repo, and rapid/cancelled
  deploys interrupted a write to `/data/apex_tracking.db`, leaving an invalid
  SQLite header. SQLite then raised 'file is not a database' on every open,
  silently disabling tracking and the signal evaluator (so calibration/review
  had no data).
- `signal_evaluator.mark_due_signals()` SELECTed `pine_signals` without
  guaranteeing `init_signal_eval_db()` had run first; on a fresh/replaced DB the
  scanner thread could query before init -> 'no such table: pine_signals'.

## Added
- `engine/db_resilience.py` — `ensure_healthy_db(path)`: cheaply detects a
  corrupt SQLite file (invalid header) and renames it aside to
  `<path>.corrupt-<UTC>.bak` so the app recreates a fresh DB. Never deletes data;
  leaves healthy or unknown-error files untouched.

## Modified
- `signal_evaluator.py` — heal + cached self-init (`_ensure_ready()`), called at
  the top of `mark_due_signals`, `scorecard`, and `record_signal`. Table
  creation is now independent of startup ordering, and a corrupt DB is
  quarantined before use.

## Manual steps (see DEPLOYMENT.md)
- Apply the small app.py heal snippet (optional but recommended).
- `git rm --cached apex_tracking.db` and add the .gitignore lines
  (gitignore_additions.txt) so a DB is never committed again.
- Clear the corrupt file on the Render disk once.
