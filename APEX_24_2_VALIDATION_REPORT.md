# APEX 24.2 Validation Report

All results were produced by executing the test suite and booting the app.

## Test execution

- New APEX 24.2 tests: 14 passed (`tests/test_institutional_replay_v242.py`,
  `tests/test_institutional_replay_v242_routes.py`).
- Complete authoritative `tests/` suite: **1,064 passed, 0 failed**
  (1,050 before APEX 24.2).
- Import mode: `--import-mode=importlib` (pre-existing duplicate-basename
  workaround; not introduced here).

## Application boot + route verification

Startup printed:
`APEX 24.2 Institutional Replay & Simulator routes registered (5 canonical routes verified).`

Canonical `/api/replay/*` surface (no duplicate routes; legacy preserved):

| Method | Path | Owner |
|---|---|---|
| GET | /api/replay/status | 24.2 |
| GET | /api/replay/session | 24.2 (dispatches to legacy intraday on ?ticker/date) |
| GET | /api/replay/trade | 24.2 |
| GET | /api/replay/timeline | 24.2 |
| POST | /api/replay/simulator | 24.2 |
| POST | /api/replay/capture | 24.2 (supporting) |
| GET | /api/replay/navigate | 24.2 (supporting) |
| GET | /api/replay/frame | legacy (unchanged) |
| GET | /api/replay/narrative,/consensus,/thesis,/decision | roadmap (unchanged) |

## Endpoint smoke results (HTTP status)

- 200 `GET /api/replay/status`
- 200 `POST /api/replay/capture` (created=True)
- 200 `GET /api/replay/session?session_id=...`
- 200 `GET /api/replay/timeline?session_id=...`
- 200 `GET /api/replay/trade?session_id=...`
- 200 `GET /api/replay/navigate?...&action=STEP_FORWARD`
- 200 `POST /api/replay/simulator`
- Legacy `GET /api/replay/session?ticker=SPX&date=...` returns the intraday
  payload (frames key present).

## Immutability + simulator isolation (tested)

- Re-capturing an existing `session_key` returns `IMMUTABLE_EXISTS` with the same
  session id and hash.
- Running the simulator creates zero new sessions and leaves the session
  integrity hash unchanged (`history_modified: false`, `records_written: 0`).

## Migration

New SQLite tables `apex_replay_sessions_v242` and `apex_replay_events_v242` are
created idempotently in the governance DB. No manual migration required.
