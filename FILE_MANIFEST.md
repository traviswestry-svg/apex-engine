# APEX 25.4 — FILE MANIFEST

Extract directly into the repository root (repo-relative paths preserved).
Apply on top of a repository that already contains the 25.2 and 25.3 deltas.

## NEW
- engine/institutional_decision_review_v254.py
- engine/institutional_decision_review_v254_routes.py
- tests/test_institutional_decision_review_v254.py
- tests/test_institutional_decision_review_v254_routes.py

## MODIFIED
- app.py                                  (adds 25.4 import + registration; cumulative through 25.4)
- engine/configuration_governance.py      (registers APEX_DECISION_REVIEW_DB + APEX_OPERATOR_TOKEN; cumulative)

## REMOVED
- (none) — see REMOVED.txt
