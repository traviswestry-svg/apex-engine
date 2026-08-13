# APEX 11.0A — Production Data Integrity (Release Manager)

**Status:** complete. Full suite **638 passed / 0 failed**.
**Phase goal (from the roadmap):** *"No new intelligence until data integrity is
trusted."* This is the gate the rest of 11.0 builds behind.

---

## Why this comes first

Every statistic in Phase 11.1 — win rate, expectancy, Sharpe, Kelly, calibration —
is a computation over stored history. Over an empty table, those modules do not
crash. They report a confident number derived from nothing. So before any of them
is built, three questions have to be answerable, and answerable *honestly*:

    What is actually deployed?        -> release_metadata()
    Is the schema what code expects?  -> migration_status()
    Is the pipeline actually writing? -> data_integrity()

## What the ZIP arrived as

The uploaded ZIP **did not collect** — the whole suite was red:

```
ImportError: cannot import name 'migration_status'       from engine.release_manager
ImportError: cannot import name 'register_release_routes' from engine.release_routes
```

`release_manager.py` and `release_routes.py` were stubs exporting a fraction of
what their tests imported. Both are now complete.

## The honest-schema principle

APEX has **no migration framework**: tables are created with CREATE TABLE IF NOT
EXISTS and evolved with ad-hoc ALTER. There is no `schema_version` table, and
`PRAGMA user_version` is never stamped. So a declared schema version is an
**operator claim, not a measurement** — and the module reports it that way:

- `verified: true` only when the version was actually read from the database.
- An operator claim (`APEX_DATABASE_SCHEMA_VERSION`) that matches → `ready: true`
  but `verified: false`. Matched, but from a claim, not a measurement.
- Neither stamped nor declared → `ready: false`. "We didn't check" is reported as
  not-ready, never as a pass.

This is the same discipline as the flow work: unknown is never silently treated
as good.

## data_integrity — the actual point of 11.0A

Names every store an 11.1 module depends on, its row count, and **what breaks if
it stays empty**:

```
premium_recommendations   EMPTY   <- Recommendation calibration needs graded history
apex_signals              MISSING <- Strategy intelligence: win rate, expectancy
flow_features             EMPTY   <- Similarity engine: pre-decision vectors
flow_labels               EMPTY   <- Similarity + calibration: outcomes
replay_snapshots          EMPTY   <- Historical replay
...
statistics_supportable: false
```

A zero reports its own consequence instead of being a bare zero. `statistics_supportable`
is the one flag the 11.1 modules should gate on.

## Endpoints (all GET-only, read-only)

| Route | Reports | Fresh-deploy status |
|---|---|---|
| `/api/system/version` | semantic + application + DB version | 200 |
| `/api/system/build` | commit, build id, environment | 200 |
| `/api/system/features` | feature list | 200 |
| `/api/system/migrations` | schema match, verified flag, pending | **503** (unstamped) |
| `/api/system/integrity` | per-store row counts + consequences | **503** (stores empty) |
| `/api/system/release` | full metadata | 200 |

`ok:true` means "the endpoint answered"; health lives in the payload
(`ready`, `statistics_supportable`). A 503 still carries `ok:true` with the
failure in the body — this surface must stay up precisely when something beneath
it is wrong. **POST → 405** on every route. The 503s on a fresh deploy are
correct: they are the signal not to build statistics yet.

## Guardrails

Every payload carries `guardrails: {read_only: true, applies_migrations: false,
changes_trade_decisions: false}`. A release endpoint that could apply a migration
is one that could break a live session. It reports; it never acts.

## Files

**Rewritten:** `engine/release_manager.py` (was a stub), `engine/release_routes.py`
(was a stub)
**Modified:** `app.py` — log line lists the new endpoints; registration unchanged
(`register_release_manager_routes` still imported and called; it now aliases
`register_release_routes`, so all six endpoints register).
**Tests:** `tests/test_release_manager.py` (+3), `tests/test_release_routes.py` (+3)

## Backward compatibility

`app.py` imports `register_release_manager_routes` and `APP_VERSION` — both
preserved. `get_release_metadata()` retained as an alias of `release_metadata()`.
No existing route changed. No schema changed. Nothing removed.

## Also fixed in this pass (pre-existing, blocking collection)

- **8 date-rot failures (mine).** `test_flow_pl` / `test_feature_store_writer`
  hardcoded expiration `2026-07-17`; the date rolled and `is_expired()` began
  skipping every chain fetch. Replaced with relative `_future_exp()` helpers that
  cannot rot. Same bug class flagged twice in review then shipped — now guarded.
- **range_intelligence order-dependent failure.** Bound `RANGE_DB_PATH` at import
  time, so storage depended on which importer won the race. Fixed to resolve
  lazily at call time (`_db_path()`), matching the pattern used here.
- **Orphaned director fork** (`engine/contracts.py`, `engine/persistence.py`)
  removed again — 4th recurrence. Zips can't express deletion; these must be
  deleted from the repo itself.

## Next

- **11.0B** — feed the chain-quality gate into premium pricing so a DEGRADED
  chain can't outrank a verified one, and fix the gate's vacuous freshness
  component (quote_age never extracted from Polygon → scores 100).
- **11.0C** — Modules 2, 3, 8, 10 (live-state, no history).
