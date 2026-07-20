# APEX 25.4 — ROLLBACK

25.4 is additive and advisory-only; rollback is low-risk.

## Full rollback
1. Delete the new files:
   - engine/institutional_decision_review_v254.py
   - engine/institutional_decision_review_v254_routes.py
   - tests/test_institutional_decision_review_v254.py
   - tests/test_institutional_decision_review_v254_routes.py
2. Revert `app.py` and `engine/configuration_governance.py` to their 25.3-era
   revisions (restore from version control / pre-25.4 backup).
3. Restart the app.

## Note on fail-loud registration
`app.py` registers 25.4 as required and fail-loud. Remove the engine files and
the app.py block together, or boot will raise a clear RuntimeError.

## Data
The store `apex_decision_review.db` is standalone; deleting it removes review
records and recommendations only. No shared schema was modified. Governance
audit entries written via institutional_governance persist in that module's DB
and are harmless if left.
