# APEX 24.2 — /api/replay/* API Stability Inventory

Produced per the API Stability Policy before changing any existing endpoint.

## 1. Pre-change route inventory

| Method | Path | Source | Purpose |
|---|---|---|---|
| GET | /api/replay/session | app.py | Legacy intraday frame index (?ticker=&date=) |
| GET | /api/replay/frame | app.py | Legacy single intraday frame |
| GET | /api/replay/narrative | institutional_roadmap_routes.py | Narrative replay (11.2/11.3) |
| GET | /api/replay/consensus | institutional_roadmap_routes.py | Consensus replay |
| GET | /api/replay/thesis | institutional_roadmap_routes.py | Thesis replay |
| GET | /api/replay/decision | institutional_roadmap_routes.py | Decision replay |

## 2. Consumers identified

- Frontend/templates/JavaScript: no `/api/replay/session` or `/frame` consumers
  found under `static/` or `templates/`.
- Background scanner writes intraday frames to the in-memory `REPLAY_STORE` and
  `replay_snapshots` SQLite table, read by the legacy `/session` and `/frame`
  handlers — this data path is preserved unchanged.

## 3. Changes and compatibility

- `/api/replay/session` is now owned by the canonical APEX 24.2 registrar, which
  dispatches by parameter: `session_id` -> 24.2 reconstruction;
  `?ticker=&date=` (legacy) -> the original intraday handler, preserved as a
  helper and injected via `legacy_session_provider`; no params -> 24.2 session
  index. The legacy response contract is byte-for-byte preserved for legacy
  parameters.
- `/api/replay/frame` and the roadmap narrative-replay routes are unchanged.

## 4. Breaking changes

None. The only structural change is that the legacy `/session` logic moved from a
route-decorated function to a helper invoked by the canonical route; its output
is identical for legacy parameters. No deployed screen or service is left
pointing at an outdated contract.
