# APEX 68.5.3 — Calibration Governance Store Initialization Closure

## Purpose
Close the fresh-deployment initialization gap exposed by the 68.5.2 truthful `MISSING_DB` state.

## Changes
- Evidence/governance store default now resolves through the canonical persistent SQLite path helper, using Render `/data` when available and safely migrating a legacy repository-local DB when present.
- Added an idempotent, controlled writer-side `initialize_governance_store()` boundary.
- Application composition invokes the initializer after Dynamic State route registration.
- Startup logs report initialization status, resolved path, and whether the path is on Render persistent storage.
- GET/read routes remain strictly read-only and never create a DB or schema.
- Manual calibration activation, bounded adjustments, rollback, suppression immutability, WATCH_ONLY immutability, and execution authority are unchanged.

## Expected production transition
A fresh deployment should move from `MISSING_DB` to `READY` during application startup. The governance endpoint should then report `initialized: true` and `read_available: true`, even when candidate counts are zero.
