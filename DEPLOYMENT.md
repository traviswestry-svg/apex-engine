# APEX 26.6-26.10 — DEPLOYMENT

## Prerequisites
- APEX 25.0-25.5 and 26.0-26.5 deployed. app.py is cumulative through 26.10.

## Steps
1. Extract `APEX_26_6_to_26_10_DELTA.zip` into the repository root.
2. No new env vars. Broker Intelligence reports the existing gate:
   ETRADE_ENABLE_TRADING (kill switch) and APEX_CONFIRMATION_GATED_EXECUTION_ENABLED.
3. Restart the app / Gunicorn. Expect on boot:
   `APEX 26.6-26.10 Execution Intelligence Suite part 2 routes registered
   (11 canonical routes verified, advisory-only).`
4. Verify `GET /api/trader-mode/current` returns the aggregated platform view
   with `production_effect: NONE`.

## How it fits
Command Center (26.9) and Trader Mode (26.10) are read-only aggregators over the
whole 25.x + 26.x stack — the institutional workstation view. Broker Intelligence
(26.7) surfaces broker preview/health only; placement stays on the existing
confirmation-gated `/api/trade/spx/*` route.

## Post-deploy checks
- Part-2 routes respond 200; existing execution/broker behavior unchanged.
- No new scanner process.
