# Apex Engine v1.5 Render Deployment

## Files
- `apex_engine_v1.py`
- `requirements.txt`
- `render.yaml`

## Render Cron Job Settings
- Runtime/Language: Python 3
- Build Command: `pip install -r requirements.txt`
- Start Command: `python apex_engine_v1.py`
- Schedule: `*/30 13-21 * * MON-FRI`

## Required Environment Variables
- `POLYGON_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Optional Environment Variables
- `MAX_RISK_PER_TRADE=750`
- `ACCOUNT_SIZE=60000`
- `SEND_TELEGRAM=true`

## Notes
- Benzinga is disabled in this build.
- SPX remains in the ticker list but is safely skipped until Polygon Indices entitlement is added.
- Only A+ actionable ideas are output. No ticker shown means no trade.
