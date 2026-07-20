# APEX 26.0 — DEPLOYMENT

## Prerequisites
- APEX 25.0-25.5 deployed. The 26.0 app.py is cumulative through 26.0.

## Steps
1. Extract `APEX_26_0_DELTA.zip` into the repository root (paths preserved).
2. No new env vars required. Sizing honors your existing TRADE_MAX_CONTRACTS /
   TRADE_MAX_RISK_PER_TRADE / TRADE_MAX_DAILY_LOSS / TRADE_MAX_SPREAD_PCT and the
   ETRADE_REQUIRE_CONFIRMATION gate.
3. Restart the app / Gunicorn. Expect on boot:
   `APEX 26.0 Execution Intelligence Core routes registered (6 canonical routes
   verified, advisory-only).`
4. Verify `GET /api/execution/status` -> `places_orders: false`,
   `confirmation_gated: true`.

## How it fits execution
26.0 produces an execution RECOMMENDATION (readiness, strategy, order type, size,
exits). To act on it, the operator uses the EXISTING confirmation-gated flow
(`/api/trade/spx/preview-entry` then place with `confirmed=true`). 26.0 never
calls those endpoints for you.

## Post-deploy checks
- Read/POST advisory routes respond 200.
- Existing `engine/execution/trade_routes` behavior is unchanged.
- No new scanner process.
