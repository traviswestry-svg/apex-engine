# APEX 3.4.3 QuantData Flow/GEX Dashboard

This build upgrades the uploaded `apex-engine-main` system without replacing the scanner.

## Added

- `/flow` — browser dashboard for QuantData institutional flow.
- `/api/flow` — JSON endpoint for SPY, QQQ, SPX by default.
- `/api/flow/<ticker>` — single ticker JSON endpoint.
- `quantdata_gex_layer()` — calls QuantData Exposure By Strike with `greekMode=GAMMA` and `representationMode=RAW`.
- `quantdata_flow_snapshot()` — combines Net Flow, Order Flow Consolidated, and GEX into one snapshot.

## QuantData endpoints used

- `POST /v1/options/tool/net-flow`
- `POST /v1/options/tool/order-flow/consolidated`
- `POST /v1/options/tool/exposure-by-strike`

## Render environment variables

Required:

```text
QUANTDATA_API_KEY=your_key_here
```

Optional:

```text
QUANTDATA_BASE_URL=https://api.quantdata.us/v1
FLOW_DASHBOARD_TICKERS=SPY,QQQ,SPX
ORDER_FLOW_ENABLED=true
GEX_ENABLED=true
RUN_SCANNER_ON_IMPORT=true
```

## How to use

1. Upload this repo to GitHub.
2. Deploy or redeploy on Render.
3. Make sure `QUANTDATA_API_KEY` is set in Render.
4. Open:

```text
https://your-render-app.onrender.com/flow
```

## Notes

- Net Flow `NET_PREMIUM` returns cents from QuantData, so this app converts to dollars.
- GEX levels are approximations from the exposure map:
  - Call wall = strike with largest call gamma exposure.
  - Put wall = strike with largest negative put gamma exposure.
  - Zero gamma = strike with net exposure closest to zero.
- This is not investment advice.
