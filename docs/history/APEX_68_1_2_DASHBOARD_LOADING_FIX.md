# APEX 68.1.2 — Dashboard Loading Fix

## Root cause

The Institutional OS composition synchronously refreshed Polygon `I:BPSPX` on
every dashboard request. Each call could block for up to 20 seconds, while
dashboard polling could stack additional requests during a Render cold start.

## Correction

- Removes Polygon BPSPX I/O from the dashboard request path.
- Returns the latest canonical breadth snapshot immediately.
- Refreshes BPSPX in one daemon worker.
- Throttles provider attempts to five minutes by default.
- Prevents duplicate in-flight refreshes.
- Preserves fail-closed missing/stale BPSPX behavior.
