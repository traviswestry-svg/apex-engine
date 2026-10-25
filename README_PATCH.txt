APEX 66.3.4 corrected object-rendering hotfix

This package fixes the GitHub CI failure where the regression test was present but engine/decision_intelligence.py remained on the pre-fix implementation.

Replace these files at the exact repository paths:
- engine/decision_intelligence.py
- templates/apex_os.html
- tests/test_decision_intelligence.py

Expected behavior:
- structured evidence dicts are normalized to readable dashboard bullets
- frontend has a defensive structured-value formatter
- test_structured_evidence_is_normalized_for_dashboard passes

No decision, execution, broker, risk, or HLCE logic is changed.
