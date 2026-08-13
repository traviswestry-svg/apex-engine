# APEX 3.1 Existing Render Service Upgrade

This package is intended to upgrade the already-deployed APEX service, not create a second dashboard service.

## Important

Do **not** deploy `apex-dashboard-main` as a separate Render service. The dashboard is already served by Flask at `/` from `app.py`, and live JSON is served at `/dashboard.json`.

## Existing Render Service Checklist

Before pushing this upgrade to the existing service, manually confirm these env vars in the Render dashboard:

- `RUN_SCANNER_ON_IMPORT=true`
- `SEND_TELEGRAM=true` if you want live alerts
- `POLYGON_API_KEY`
- `QUANTDATA_API_KEY`
- `BENZINGA_API_KEY` if available
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Existing Render services usually do not auto-merge new `render.yaml` env vars into the service. That is why `RUN_SCANNER_ON_IMPORT=true` should be added manually before deploy.

## Deploy

Push the contents of this folder to the same GitHub repo connected to the existing APEX Render service. Do not create a new repo or new Render service.

## Verify

After deploy, check:

- `/health`
- `/api/status`
- `/dashboard.json`

Confirm scanner startup and that `updated_at` / scan timestamps refresh without manually hitting `/api/run`.
