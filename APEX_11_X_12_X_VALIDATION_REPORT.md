# APEX 11.x–12.x Validation Report

- Baseline extraction: passed
- Architecture and persistence inspection: passed
- Python syntax/compile validation: passed
- Import validation: passed
- Flask route registration: passed
- Registered Flask routes after build: 201
- SQLite schema initialization: passed
- Idempotent schema initialization: passed
- API smoke tests: passed
- Dashboard template smoke tests: passed
- Historical empty/threshold/quality states: passed
- Immutable outcome duplicate guard: passed
- Feature hash/version tests: passed
- Similarity look-ahead guard: passed
- Adaptive disabled-state test: passed
- Candidate approval gate: passed
- Rollback and audit tests: passed
- Full test suite: **695 passed, 0 failed, 0 skipped**

Validation command: `python -m pytest -q`
