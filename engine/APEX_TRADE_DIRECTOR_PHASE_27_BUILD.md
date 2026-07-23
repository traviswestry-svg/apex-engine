# APEX Trade Director Phase 27 — Institutional Change Control

## Repository truth

The uploaded repository contained completed Phase 26 and Phase 28–30 implementations, but no Phase 27 engine, routes, dashboard integration, tests, or build record. Phase 28's lineage registry explicitly identified Phase 27 as `change_control`, confirming this was an implementation gap rather than a roadmap renumbering.

## Added

- `engine/trade_director_change_control.py`
- Append-only SQLite change proposal and audit-event ledger
- Deterministic proposal identity and content hashing
- Validation evidence gate covering compilation, regression tests, APIs, dashboard, and ZIP integrity
- Independent-review requirement before approval
- Integrity-chain verification and tamper detection
- Trade Director coordination under `change_control`
- Change Control dashboard panel
- `/api/change-control/*` API family
- `tests/test_trade_director_phase27.py`

## APIs

- `GET /api/change-control/status`
- `GET /api/change-control/history`
- `GET /api/change-control/change/<change_id>`
- `POST /api/change-control/propose`
- `POST /api/change-control/validate`
- `POST /api/change-control/review`
- `GET|POST /api/change-control/integrity`

## State model

- `DRAFT`
- `VALIDATION_FAILED`
- `AWAITING_APPROVAL`
- `APPROVED`
- `REJECTED`
- `SUPERSEDED`

## Safety boundary

Phase 27 does not edit source files, mutate runtime configuration, deploy releases, promote policies, interact with a broker, or enable autonomous execution. It records change intent and approval evidence only. Deployment remains separately confirmation-gated.

## Compatibility

The implementation is additive. No existing endpoint, import path, dashboard panel, decision gate, risk limit, or execution behavior was removed or changed.

## Repository implementation audit

### Completed

- Phases 1–26 have build records and corresponding implementation surfaces.
- Phases 28–30 are implemented and integrated.
- Phase 20.1 architecture consolidation is present.
- Confirmation gating remains intact; no live autonomous broker submission path was added.

### Partial or environment-gated

- The full Flask/API runtime test suite requires the dependencies declared in `requirements.txt`. The audit container could not install packages because its package index is unavailable, so Flask-dependent collection could not be executed here.
- Market-closed frontend verification remains listed as deferred in `BACKLOG.md` and requires a deployed browser/DevTools validation.
- Data-driven learning calibration remains dependent on accumulated outcome data, as documented in `BACKLOG.md`.

### Missing component resolved

- Phase 27 Change Control was referenced by Phase 28 lineage but absent from implementation. This build supplies the missing engine, APIs, dashboard, persistence, tests, documentation, and coordination state.

### Technical debt corrected

- Removed the exact duplicate root-level `test_trade_director_phase23.py`; the canonical `tests/test_trade_director_phase23.py` remains. This restores compliance with the repository architecture guard.
- Corrected the Lineage dashboard data source to render the coordinated Trade Director response instead of the Phase 26 command-center response.

## Validation results

- Python compilation: **passed** (`python -m compileall`)
- Trade Director Phase 13–30 regression slice: **69 passed, 0 failed**
- Broader non-Flask suite: **1000 passed; 3 environment-blocked failures** caused solely by missing Flask imports
- JavaScript syntax validation: **passed** (`node --check` on the dashboard script)
- Static API registration validation: **passed**
- Static dashboard integration validation: **passed**
- Architecture duplicate-file finding: **resolved**
- Live Flask endpoint execution: **not run in this container because Flask could not be installed from the unavailable package index**

## Upgrade notes

1. Deploy the full repository artifact as usual through GitHub/Render.
2. The new change-control database defaults to `/data/apex_change_control.db` when a writable Render disk is mounted; otherwise it uses the repository working directory.
3. Override the database location with `APEX_CHANGE_CONTROL_DB` when needed.
4. Existing APIs and database files require no migration.
5. Phase 27 starts empty and advisory. No release is approved until a proposal is submitted, validation evidence is recorded, and an independent reviewer approves it.
