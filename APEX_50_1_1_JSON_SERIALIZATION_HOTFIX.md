# APEX 50.1.1 — JSON Serialization Hotfix

## Root cause
APEX 50.1 exposed raw quote diagnostics containing the internal `FEED_REQUIRED` sentinel. Flask's JSON encoder cannot serialize that Python singleton, causing `/api/morning-brief` to return HTTP 500.

## Fix
Expected-move quote diagnostics now convert unavailable bid, ask, mid, last, and IV values to JSON `null`. Internal calculation paths continue using `FEED_REQUIRED`, preserving fail-honest behavior.

## Changed files
- `engine/daily_key_levels_adapters.py`
- `tests/test_apex50_1_1_json_safe_diagnostics.py`

## Validation
- Python compilation: PASS
- APEX 50.1 and hotfix focused tests: 5 passed
