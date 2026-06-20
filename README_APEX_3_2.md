# APEX 3.2 Institutional Engine

Production upgrade for the existing Render service connected to `traviswestry-svg/apex-engine`.

## What changed from 3.1

- Added Institutional Accumulation Score.
- Added optional QuantData dark-pool / large-print layer with safe fallbacks.
- Added Breakout Probability Score.
- Added Accumulation Watchlist status for early institutional pressure.
- Reweighted final score to include accumulation.
- Dashboard now shows Tech, Flow, Dark, Accumulation, Breakout Probability, Catalyst, Relative Strength, Regime, and RVOL.
- Telegram alerts include accumulation and breakout probability.
- Kept existing-service behavior: no new Render service required.

## Existing Render service upgrade

Keep using the current Render service:

`apex-engine-dashboard`

Connected repo:

`traviswestry-svg/apex-engine`

Important env var:

`RUN_SCANNER_ON_IMPORT=true`

Do not rely on render.yaml to add new env vars to an existing service. Add missing vars manually in Render.

## Optional env vars

```text
QUANTDATA_API_KEY=<your key>
QUANTDATA_BASE_URL=https://api.quantdata.us/v1
BENZINGA_API_KEY=<your key>
MIN_FINAL_SCORE=78
MIN_ALERT_SCORE=85
MIN_ACCUMULATION_SCORE=68
PREBREAKOUT_DISTANCE_PCT=2.0
DARK_POOL_ENDPOINT_ENABLED=true
```

If the dark-pool endpoint is unavailable on your QuantData plan, APEX returns a neutral dark-pool score and continues scanning.
