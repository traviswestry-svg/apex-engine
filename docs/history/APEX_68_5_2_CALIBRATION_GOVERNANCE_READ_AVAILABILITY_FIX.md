# APEX 68.5.2 — Calibration Governance Read Availability Fix

## Purpose
Preserve the 68.5.1 nonblocking calibration read path while making read availability truthful and actionable.

## Changes
- Missing evidence/calibration DB now returns `MISSING_DB` as a normal pre-initialization state.
- Existing evidence DB without governance schema returns `EMPTY_NOT_INITIALIZED`.
- SQLite lock/busy failures return `BUSY` and remain degraded/observable.
- Other SQLite/read failures return `READ_ERROR` and remain degraded/observable.
- Calibration activation, governance, and outcome-calibration readouts share the same availability semantics.
- Missing/uninitialized stores never create schema from GET/read paths.
- Eligibility remains heuristic while the store is missing/uninitialized.

## Safety
No trading thresholds, direction logic, execution authority, broker/risk behavior, automatic promotion, or automatic activation were changed.
