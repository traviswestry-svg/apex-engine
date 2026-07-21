# APEX Institutional OS Worker-Isolation Fix

## Replace these files

- `app.py`
- `static/js/apex_os.js`

## What changed

1. `/api/institutional_os` is now a cache-only browser endpoint. It never runs the heavy nine-engine composition in a Gunicorn request thread.
2. A single daemon composer refreshes each ticker in the background. Duplicate browser polls cannot launch duplicate compositions.
3. The last good cache is returned immediately while background refresh is running.
4. Cold starts return a truthful `warming` payload without blocking the site.
5. Volume-profile composition is bounded and detached from the request lifecycle.
6. The legacy second full-pipeline fallback was removed. Failures return the last good cache or a degraded payload.
7. Scanner-side composition defaults to disabled to prevent competition with the dedicated composer.
8. A delayed post-start warm-up primes SPX without delaying Render's health check.
9. Frontend retries are single-flight and do not render the warming placeholder as institutional data.
10. Static asset version was bumped so browsers receive the corrected JavaScript.

## Recommended Render environment values

```text
COMPOSE_IOS_IN_SCANNER=false
WARM_IOS_ON_IMPORT=true
IOS_WARM_DELAY_SECONDS=12
IOS_CACHE_TTL_SECONDS=15
IOS_FETCH_TIMEOUT_SECONDS=3
```

Remove any existing `COMPOSE_IOS_IN_SCANNER=true` override, because an environment variable overrides the new safe code default.

## Deploy

Commit the two files, then use **Manual Deploy → Clear build cache & deploy** once.

After deployment, the first visit may show `Engines warming in the background` briefly. The site must remain reachable during that warm-up and should not require another redeploy.
