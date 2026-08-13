# APEX 24.1 Changed File Manifest

## Added

- `engine/institutional_portfolio_risk_v241.py`
- `engine/institutional_portfolio_risk_v241_routes.py`
- `tests/test_institutional_portfolio_risk_v241.py`
- `tests/test_institutional_portfolio_risk_v241_routes.py`
- `APEX_24_1_IMPLEMENTATION_REPORT.md`
- `APEX_24_1_VALIDATION_REPORT.md`
- `APEX_24_1_FILE_MANIFEST.md`
- `APEX_24_1_DEPLOYMENT_ROLLBACK.md`
- `APEX_24_1_API_STABILITY_INVENTORY.md`

## Modified

- `app.py` — 24.1 import guard (with verifier); removed 24.1 registration from
  the broad non-fatal try/except and added a dedicated fail-loud registration
  block with canonical-route verification.
- `engine/configuration_governance.py` — registered 7 governed 24.1 risk-budget
  variables.
- `engine/institutional_mission_control_v213.py` — `PORTFOLIO_INTELLIGENCE`
  panel, detail block, and drill-down.
- `engine/institutional_roadmap_routes.py` — moved `/api/portfolio-risk/status`
  and `/evaluate` ownership to the canonical 24.1 engine; retained the immutable
  `/record` and `/history` endpoints.
- `engine/release_manager.py` — release identity bumped to
  `17.1.0_INSTITUTIONAL_PORTFOLIO_RISK_INTELLIGENCE`.
- `tests/test_apex16_3_portfolio_risk_intelligence.py` — updated the route
  contract test to reflect canonical 24.1 ownership (same-change consumer update
  per the API Stability Policy).
