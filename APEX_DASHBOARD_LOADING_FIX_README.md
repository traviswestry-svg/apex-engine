# APEX Dashboard Loading Fix

Changed files:
- `app.py`
- `static/js/apex_os.js`

Corrections:
1. Disabled scanner-driven Institutional OS composition by default to prevent contention on Render's single Gunicorn worker. It can be re-enabled with `COMPOSE_IOS_IN_SCANNER=true` after scaling workers.
2. Added a real fresh-cache fast path so browser polling does not recompute the full institutional pipeline on every request.
3. Added a hard timeout around `_volume_profile_bundle`, which was previously called without a timeout and could block the worker indefinitely.
4. Removed the unbounded legacy fallback after a nine-engine failure. The route now returns the last good cache or a truthful degraded startup response.
5. Prevented `refresh_in_progress` and `warming` control payloads from being stored and rendered as real dashboard data.
6. Increased the browser request timeout to 15 seconds and shortened cold-start retries to 3 seconds.

Deployment:
Copy both files to the same paths in GitHub, commit, then use Render > Manual Deploy > Clear build cache & deploy.

Validation performed:
- `python -m py_compile app.py` passed.
- `node --check static/js/apex_os.js` passed.
- Full pytest collection was not available in the inspection environment because Flask is not installed there.
