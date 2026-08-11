APEX Decision Intelligence [object Object] rendering fix

Changed files:
- engine/decision_intelligence.py
- templates/apex_os.html
- tests/test_decision_intelligence.py

Root cause:
Decision Intelligence Q5 (Why?) can contain structured evidence dictionaries. The
legacy renderer passed those dictionaries directly through String(), producing
"[object Object]" in the browser.

Fix:
1. Backend normalizes structured evidence to stable human-readable bullet text.
2. Frontend adds a defensive structured-answer formatter so future object-valued
   evidence cannot leak as "[object Object]".
3. Regression test covers dict evidence.

No trading/execution logic is modified.
