# APEX 43.5 — Temporary Intelligence Mesh Diagnostics

Adds a session-only engineering panel to the Institutional Command Center.

## Included
- Engine contribution table: direction, raw score, weight, freshness, reliability, signed contribution
- Mesh health: coverage, agreement, pre-penalty confidence, conflict penalty, final confidence
- Rolling browser-local decision timeline (up to 50 evaluations)
- Temporary calibration sandbox for thresholds and engine enable/disable
- CSV timeline and JSON full-session exports
- No database migration, environment variable, persistent calibration, or broker action

## Routes
- Existing POST `/api/intelligence-mesh` now accepts optional `calibration`
- Command Center aliases include `/command_center`, `/apex42`, `/apex43`, `/apex43.5`
