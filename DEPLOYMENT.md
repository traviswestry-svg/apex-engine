# Deploy

## If you are on the full 25.2-26.10 stack (you deployed the reconcile bundle)
Extract this zip's app.py + tests/ into the repo root, commit, push, deploy once.

## If you are on 25.4 (or any other version)
Do NOT use this zip's app.py (it registers 25.5/26.x). Instead apply the three
edits in PATCH.md to your running app.py, add tests/test_ios_single_flight.py,
commit, push, deploy once.

## Verify after deploy
- DevTools Console: the '/api/institutional_os timed out after 6s' loop is gone.
- Network: API calls complete (non-zero size) instead of hanging pending.
- Optional: GET /api/institutional_os?ticker=SPX twice quickly — the second
  returns fast with "status":"refresh_in_progress" while the first computes.

## Reminder
This matters most under load / at the open. Pre-market it also just means the
panels fill once the first compose finishes instead of the UI hammering itself.
Deploy ONCE and let it finish.
