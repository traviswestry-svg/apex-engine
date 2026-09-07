# APEX 68.5.1 — Dynamic-State Runtime Nonblocking Fix

## Purpose
Prevent dynamic-state and calibration observability requests from stalling behind evidence-store writer activity.

## Changes
- Dynamic-state calibration activation reads now use a true read-only canonical SQLite connection with a 350 ms connect timeout and 250 ms busy timeout.
- Runtime policy resolution fails soft to the existing heuristic policy if the activation store is busy/unavailable.
- Read paths no longer create schema, heal databases, or mutate WAL/journal state.
- Calibration activation and eligibility status are computed with lightweight read-only queries.
- Governance and calibration summary GET paths use bounded read-only access.
- Canonical persistence now supports a per-connection busy-timeout override while preserving the existing default for all current callers.

## Safety
No direction, suppression, WATCH_ONLY, risk, broker, execution-authority, calibration bounds, approval requirements, or HLCE behavior changed. Activation and rollback writes remain governed write operations.
