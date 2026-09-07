# APEX 25.2 -> 26.10 Reconcile Bundle

## Why this exists
Your deploy crash-loops with:
  Error: APEX 25.5 ... routes are required but the module failed to import
  No module named 'engine.institutional_validation_promotion_v255_routes'
  No module named 'engine.execution_suite_v26x_routes'

Cause: your deployed app.py contains the 25.5 + 26.x registration blocks, but the
engine files those blocks import were not in the pushed commit (a partial commit —
you pushed the newer app.py but not all the new engine/*.py modules). The 25.5
block is fail-loud by design, so it refuses to boot half-wired.

This bundle is the COMPLETE, tested-together set: every engine/route module from
25.2 through 26.10, the DB-resilience hotfix, the matching app.py and
configuration_governance.py, plus .python-version. Extracting it makes app.py and
its required modules consistent.

## Contents
- engine/  : 23 modules (25.2-25.5, 26.0-26.10, db_resilience, configuration_governance)
- signal_evaluator.py, app.py  : cumulative through 26.10 + DB heal
- tests/   : 13 test files (all pass: full suite 1299 passed on a clean base)
- .python-version (3.12.11), gitignore_additions.txt

## Verified
Extracted onto a clean repo, the app imports with 702 routes and the full suite
reports 1299 passed (1 pre-existing unrelated refusal_replay test deselected).

## Deploy (the important part is committing ALL of it)
1. Extract into the repository ROOT (paths are preserved: engine/... , tests/... ,
   app.py, signal_evaluator.py, .python-version).
2. Stage EVERYTHING and confirm the new modules are tracked:
     git add -A
     git status                       # expect the new engine/*.py files listed
     git ls-files engine/ | grep -E 'v255|v26'   # must NOT be empty
3. Append gitignore_additions.txt to .gitignore, and stop committing the DB:
     git rm --cached apex_tracking.db
4. Commit and push:
     git commit -m "Reconcile 25.2-26.10 engine modules + DB hotfix + py3.12 pin"
     git push
5. In Render: confirm PYTHON_VERSION=3.12.11, then deploy ONCE and let it finish.

## Expected boot log
...25.4 registered...
APEX 25.5 Institutional Validation & Promotion routes registered (12 canonical...)
APEX 26.0 Execution Intelligence Core routes registered (6 canonical...)
APEX 26.1-26.5 Execution Intelligence Suite routes registered (14 canonical...)
APEX 26.6-26.10 Execution Intelligence Suite part 2 routes registered (11 canonical...)
No 'file is not a database' / 'no such table: pine_signals'.

## If instead you want to get back to a WORKING 25.4 now (rollback option)
You do not need this bundle. Just revert app.py to remove the 25.5 and 26.x
import+registration blocks (everything after the 25.4 registration block, down to
`if RUN_SCANNER_ON_IMPORT:`), keep the DB-hotfix files (engine/db_resilience.py +
signal_evaluator.py), redeploy. That boots cleanly at 25.4 with the DB fix.
