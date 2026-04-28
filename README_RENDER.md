# Apex Engine v1 - Render Deployment

## Files
- `apex_engine_v1.py` - main scanner
- `requirements.txt` - Python dependencies
- `render.yaml` - Render cron job blueprint

## Required environment variables
- `POLYGON_API_KEY`
- `BENZINGA_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Optional environment variables
- `SCAN_TICKERS` - comma-separated ticker list
- `MAX_RISK_PER_TRADE` - default 750
- `MIN_SCORE` - default 75
- `SEND_TELEGRAM` - true/false
- `DASHBOARD_OUTPUT_PATH` - default dashboard_data.json

## Render setup
1. Create a new GitHub repository.
2. Upload these files.
3. In Render, create a new Blueprint or Cron Job.
4. Add environment variables.
5. Deploy.

## Schedule note
The included cron schedule runs every 30 minutes from 13:00-21:59 UTC Monday-Friday, which roughly covers U.S. market hours depending on daylight savings.
