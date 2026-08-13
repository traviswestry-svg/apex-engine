# APEX DB Resilience Hotfix — FILE MANIFEST

Extract into the repository root (repo-relative paths preserved).
Safe on the deployed 25.4 build and on the full 25.x/26.x stack.

## NEW
- engine/db_resilience.py
- tests/test_db_resilience.py

## MODIFIED (drop-in; version-independent)
- signal_evaluator.py

## MANUAL (not auto-applied — see DEPLOYMENT.md)
- app.py            (apply the ~8-line heal snippet to init_tracking_db)
- .gitignore        (append gitignore_additions.txt)
- remove committed apex_tracking.db from git history/tracking

## REMOVED
- (none auto) — you must run: git rm --cached apex_tracking.db
