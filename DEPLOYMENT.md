# APEX 25.2 — DEPLOYMENT

## Prerequisites
- APEX 25.0 and 25.1 already deployed (this sprint imports 25.0 directly).

## Steps
1. Extract `APEX_25_2_DELTA.zip` into the repository root (paths are preserved).
2. (Optional) Set `APEX_DECISION_FORECAST_DB` to a path under your production
   data volume. If unset it defaults to `apex_decision_forecast.db`.
3. Restart the app / Gunicorn. On boot you should see:
   `APEX 25.2 Decision Outcome Forecast routes registered (6 canonical routes
   verified, shadow-mode).`
4. Verify: `GET /api/decision-forecast/status` returns `shadow_mode: true` and
   `production_effect: "NONE"`.

## Post-deploy checks
- `GET /api/decision-forecast/current` returns a forecast for the current
  `last_result` snapshot.
- Scenario probabilities in `/api/decision-forecast/scenarios` sum to 100.
- No new scanner process starts; existing health/replay/signal-log endpoints
  remain functional.

## Rollout note
25.2 is shadow-only and safe to run in production immediately; it cannot affect
execution. Let forecasts accumulate and mature before any future promotion work.
