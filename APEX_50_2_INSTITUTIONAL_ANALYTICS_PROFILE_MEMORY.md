# APEX 50.2 — Institutional Analytics & Profile Memory

## Implemented
- Deterministic, transparent internal level analytics for strength, reaction, break, reversal, and magnet context.
- Scores are explicitly heuristics, not calibrated win probabilities.
- Expected Move confidence now follows the actual option quote-quality diagnostic even when ATM IV is unavailable.
- Persistent daily volume-profile archive with Previous POC and rolling composite POC/VAH/VAL.
- Profile archive uses `APEX_GOVERNANCE_DB` and therefore survives Render restarts when `/data` is mounted.
- Neutral/short/long gamma terminology continues to use the canonical provider regime.

## Changed files
- `app.py`
- `engine/daily_key_levels.py`
- `engine/daily_key_levels_adapters.py`
- `engine/level_analytics.py` (new)
- `engine/profile_history.py` (new)
- `tests/test_apex50_2_institutional_analytics.py` (new)

## Deployment
Set `APEX_GOVERNANCE_DB=/data/apex_governance.db` with a persistent disk mounted at `/data`.
The profile-history fields populate after at least one prior session has been archived.
