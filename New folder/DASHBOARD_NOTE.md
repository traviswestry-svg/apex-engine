# Dashboard Note

The separate `apex-dashboard-main` folder contains an older static dashboard (`index.html` + static `dashboard.json`). It should not be deployed as the production dashboard for APEX 3.1.

APEX 3.1 serves the production dashboard directly from Flask:

- `/` = live dashboard
- `/dashboard.json` = live scanner state JSON
- `/api/status` = status/debug JSON
- `/api/run` = manual scan trigger

Keeping the static dashboard around can cause confusion because it will show stale empty data unless manually updated.
