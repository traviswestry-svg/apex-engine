# APEX DB Resilience Hotfix — DEPLOYMENT

## 1. Extract
Extract into the repo root. This adds engine/db_resilience.py and updates
signal_evaluator.py (safe on your current 25.4 build).

## 2. Apply the app.py heal snippet (recommended)
In app.py, inside `init_tracking_db()`, right after the
`os.makedirs(db_dir, exist_ok=True)` line and BEFORE `conn = get_db_connection()`,
insert:

    try:
        from engine.db_resilience import ensure_healthy_db as _ensure_healthy_db
        _ensure_healthy_db(DB_PATH)
    except Exception:
        pass

(signal_evaluator already heals its own path, so this is belt-and-suspenders for
the tracking DB.)

## 3. Stop committing the database
    git rm --cached apex_tracking.db
Then append the lines from gitignore_additions.txt to your .gitignore, commit,
and push. A binary DB in git is what shipped a stale file and, combined with
interrupted deploys, produced the corruption.

## 4. Clear the corrupt file on the Render disk (one time)
The existing /data/apex_tracking.db is invalid ('file is not a database'), so
nothing is recoverable from it. In a Render shell (or one-off job):
    mv /data/apex_tracking.db /data/apex_tracking.corrupt.bak
On next boot the app recreates a fresh DB and the evaluator creates pine_signals.
(After this hotfix, even if you skip this step, the heal will quarantine it
automatically on first use.)

## 5. Deploy hygiene
Deploy ONCE and let it finish. The log showed many overlapping 'Deploy cancelled'
events and a 'Port scan timeout' — overlapping deploys interrupting a disk write
are how the DB got corrupted. Avoid stacking deploys.

## Verify after deploy
- Boot log no longer shows 'file is not a database' or 'no such table: pine_signals'.
- After some signals arrive: GET the signal scorecard endpoint returns counts > 0.
- Confirm DB_PATH and SIGNAL_EVAL_DB_PATH resolve to the SAME /data file.
