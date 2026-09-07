# APEX 45.1 — Morning Brief Route Fix

## Fixed

- Added the missing `GET /api/morning-brief` Flask route requested by `templates/execution_os.html`.
- Added `?refresh=1` cache bypass support.
- Wired the route to `engine.morning_brief.generate_morning_brief`.
- Reused APEX flow, daily bars, 1-minute bars, and volume-profile providers.
- Added ET-session caching and a generation lock to prevent duplicate paid narrative requests.
- Preserved deterministic-only output when `ANTHROPIC_API_KEY` or optional feeds are unavailable.
- Added bounded concurrent provider retrieval and explicit JSON errors instead of a 404.

## Deployment

Replace `app.py`, commit, and redeploy Render. No frontend change is required because the dashboard already requests the correct endpoint.
