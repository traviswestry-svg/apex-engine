# APEX 3.1 Institutional Forecast Engine

APEX 3.1 is the production-hardened version of APEX 3.0 with two important upgrades:

1. **Clean scanner startup** — importing `app.py` no longer starts a live scanner. Render/Gunicorn starts it only when `RUN_SCANNER_ON_IMPORT=true` is set. This prevents duplicate scanner threads, accidental API usage, and Telegram alerts during tests or CLI imports.
2. **Greek-aware option sizing** — contract size is now based on the actual stock stop and Polygon option snapshot Greeks (`delta`, `gamma`, `iv`) instead of a mostly-flat 20%-30% premium stop assumption.

## Main endpoints

- `/` dashboard
- `/dashboard.json` full state
- `/api/status` scanner status
- `/api/run` manual scan
- `/health` health check

## Required environment variables

- `POLYGON_API_KEY`
- `QUANTDATA_API_KEY` optional but recommended
- `BENZINGA_API_KEY` optional
- `TELEGRAM_BOT_TOKEN` optional
- `TELEGRAM_CHAT_ID` optional
- `RUN_SCANNER_ON_IMPORT=true` for Render web service scanner loop

## Key risk settings

- `ACCOUNT_SIZE=60000`
- `MAX_RISK_PER_TRADE=750`
- `MIN_FINAL_SCORE=78`
- `MIN_ALERT_SCORE=85`
- `SCAN_INTERVAL_SECONDS=300`

## Notes

The scanner uses a mutex to prevent overlapping manual and background scans. Shared dashboard state is protected by a lock. Render should stay at one Gunicorn worker unless you move the scanner to a separate worker service.
