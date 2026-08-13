# APEX 24.1 Validation Report

All results below were produced by executing the repository test suite and
booting the application; none are fabricated.

## Test execution

- New APEX 24.1 engine + routes tests: 27 passed
  (`tests/test_institutional_portfolio_risk_v241.py`,
  `tests/test_institutional_portfolio_risk_v241_routes.py`, plus the updated
  `tests/test_apex16_3_portfolio_risk_intelligence.py` contract test).
- Complete authoritative `tests/` suite: **1,050 passed, 0 failed**
  (baseline before APEX 24.1 was 1,029 passed).
- Import mode: `--import-mode=importlib` (works around a pre-existing duplicate
  test basename between `templates/test_dependency_governance.py` and
  `tests/test_dependency_governance.py`; not introduced by this release).

## Application boot + route verification

Booted with `DISABLE_BACKGROUND_SCANNER=true RUN_SCANNER_ON_IMPORT=false`.
Startup printed: `APEX 24.1 Institutional Portfolio & Risk Intelligence routes
registered (6 canonical routes verified).`

Canonical `/api/portfolio-risk/*` surface (no duplicate routes):

| Method | Path | Owner |
|---|---|---|
| GET | /api/portfolio-risk/status | 24.1 |
| GET | /api/portfolio-risk/exposure | 24.1 |
| GET | /api/portfolio-risk/budget | 24.1 |
| GET | /api/portfolio-risk/opportunities | 24.1 |
| POST | /api/portfolio-risk/evaluate | 24.1 |
| POST | /api/portfolio-risk/allocation | 24.1 |
| POST | /api/portfolio-risk/prioritize | 24.1 |
| POST | /api/portfolio-risk/record | 16.3 (preserved) |
| GET | /api/portfolio-risk/history | 16.3 (preserved) |

## Endpoint smoke results (HTTP status)

- 200 `GET /api/portfolio-risk/status`
- 200 `GET /api/portfolio-risk/exposure`
- 200 `GET /api/portfolio-risk/budget`
- 200 `GET /api/portfolio-risk/opportunities`
- 200 `POST /api/portfolio-risk/evaluate`
- 200 `POST /api/portfolio-risk/allocation`
- 200 `GET /api/portfolio-risk/history`
- 201 `POST /api/portfolio-risk/record`
- 200 `GET /api/mission-control-v2/status`
- 200 `GET /health`

## Fail-loud verification

- `verify_registered` returns all six canonical routes as missing on a bare
  Flask app and an empty list on a freshly registered app (unit tested).
- Registering the 24.1 routes twice raises `AssertionError` from Flask, which
  the startup block converts to an explicit `RuntimeError` (verified manually).

## Migration

No manual database migration required. APEX 24.1 adds no new tables; it reuses
the 16.3 `portfolio_risk_snapshots` table for `/record` and `/history`.
