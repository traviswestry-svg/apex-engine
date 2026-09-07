# APEX 24.1 — /api/portfolio-risk/* API Stability Inventory

Produced per the API Stability Policy before changing any existing endpoint.

## 1. Pre-change route inventory

Before APEX 24.1, `/api/portfolio-risk/*` was served entirely by the 16.3 engine
via `engine/institutional_roadmap_routes.py`:

| Method | Path | Handler | Engine |
|---|---|---|---|
| GET | /api/portfolio-risk/status | portfolio_risk_status | 16.3 |
| POST | /api/portfolio-risk/evaluate | portfolio_risk_evaluate | 16.3 |
| POST | /api/portfolio-risk/record | portfolio_risk_record | 16.3 |
| GET | /api/portfolio-risk/history | portfolio_risk_history | 16.3 |

## 2. Consumers identified

- `tests/test_apex16_3_portfolio_risk_intelligence.py` — asserted the route
  strings existed in `institutional_roadmap_routes.py`, and exercises the
  `portfolio_risk_intelligence` engine directly (`evaluate`, `record`).
- `engine/institutional_mission_control_v213.py` — drill-down to
  `/api/portfolio-risk/status`.
- Frontend/templates/JavaScript: none found
  (`grep -rn "portfolio-risk" static/ templates/` returned no matches), so no
  deployed screen points at this contract.

## 3. Changes and compatibility

- `/status` and `/evaluate` are now served by the canonical APEX 24.1 engine.
  Response bodies are supersets of the 16.3 payloads: all previously returned
  top-level fields (`risk_state`, `risk_score`, `net_greeks`, `total_open_risk`,
  `permissions`, `advisory_only`, `broker_effect`, `orders_changed`,
  `lockout_recommended`, `default_policy`, `snapshot_count`, …) are preserved and
  new fields are added. `/evaluate` still accepts the legacy
  `{"snapshot": {...}}` envelope.
- `/record` and `/history` are unchanged (still on the 16.3 persistence layer).
- Consumer updated in the same change: the 16.3 route contract test now verifies
  the canonical routes on a live app instead of asserting file-local strings.

## 4. Breaking changes

None for response consumers. The only structural change is which module defines
`/status` and `/evaluate`; the HTTP contract is backward compatible. The one
test that asserted implementation location was updated in this same change, so
no deployed screen or service is left pointing at an outdated contract.
