# APEX 24.3 Validation Report

All results were produced by executing the test suite and booting the app.

## Test execution

- New APEX 24.3 tests: 14 passed (`tests/test_institutional_research_lab_v243.py`,
  `tests/test_institutional_research_lab_v243_routes.py`).
- Complete authoritative `tests/` suite: **1,078 passed, 0 failed**
  (1,064 before APEX 24.3).

## Boot + route verification

Startup printed:
`APEX 24.3 Strategy Research Laboratory routes registered (4 canonical routes verified).`

Canonical `/api/research/*` additions (existing findings/similarity routes untouched):

| Method | Path | Owner |
|---|---|---|
| GET | /api/research/status | 24.3 (merges legacy findings/similarity fields) |
| GET | /api/research/strategies | 24.3 |
| GET | /api/research/experiments | 24.3 |
| GET | /api/research/performance | 24.3 |
| POST | /api/research/experiments | 24.3 (create) |
| POST | /api/research/experiments/revision | 24.3 |
| POST | /api/research/analytics | 24.3 |
| GET | /api/research/dashboard | 24.3 |

## Endpoint smoke results

- 200 `GET /api/research/status` — legacy `institutional_research` and
  `institutional_similarity` fields preserved; 24.3 `offline_research_only`
  present.
- 200 `GET /api/research/strategies`, `/performance`, `/experiments`
- 200 `POST /api/research/experiments` (created=True)

## Analytics correctness (tested)

For the sample trade set, win rate 50%, gross profit 175, gross loss 75, profit
factor 175/75, expectancy 25, average R 0.5, max drawdown 50, and the equity
curve [100, 50, 125, 100] — all asserted in tests.

## Immutability + isolation (tested)

- Experiment version history is append-only; revisions add versions without
  mutating prior ones. `production_settings_modified` is false throughout.
- Re-creating an experiment by name returns `EXISTS` without a second row.

## Migration

New SQLite tables `apex_research_experiments_v243` and
`apex_research_experiment_versions_v243` created idempotently. No manual migration.
