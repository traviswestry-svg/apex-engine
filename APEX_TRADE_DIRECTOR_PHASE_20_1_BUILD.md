# APEX Trade Director Phase 20.1 — Repository & Architecture Consolidation

## Purpose

Phase 20.1 consolidates repository structure before Phase 21 trade-management work. It intentionally avoids behavioral changes to the trading engines, broker controls, provider integrations, and Render startup lifecycle.

## Changes

- Moved `test_trade_director_phase19.py` from the repository root into `tests/`.
- Removed the duplicate root copy of `test_db_resilience.py`; the canonical copy remains in `tests/`.
- Added `pyproject.toml` with deterministic pytest discovery under `tests/` and the repository root on `PYTHONPATH`.
- Added a production-safe `.gitignore` for Python caches, runtime SQLite files, logs, local environments, and secrets.
- Added `scripts/architecture_audit.py`, a dependency-free repository guard that does not import the APEX application.
- Added `tests/test_repository_architecture.py` to enforce the architecture policy in CI.
- Added `docs/architecture/PROJECT_STRUCTURE.md` defining entry points, directory ownership, root-file policy, and import-time safety rules.

## Preserved production behavior

- `wsgi.py` remains the production WSGI entry point.
- `engine.application_composition:create_app` remains the application factory.
- `scanner_worker.py` remains the explicit scanner process.
- No provider, broker, scanner, database warmup, or background task was added at import time.
- Phase 9 risk controls, Phase 10 exact confirmation, Phase 14 `STAND_DOWN`, Phase 16 execution safeguards, and Phase 20 preview-only authorization remain unchanged.

## Deployment

No new environment variables or Render service changes are required.
