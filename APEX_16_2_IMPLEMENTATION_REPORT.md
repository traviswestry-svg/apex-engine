# APEX 16.2 Implementation Report

## Adaptive Trade Management

APEX 16.2 adds deterministic, advisory-only management for an already-open trade. The engine evaluates trade progress, remaining edge, institutional confluence, pressure, market-state confidence, playbook quality, structure alignment, and explicit invalidation evidence.

### Capabilities

- Remaining Edge Score
- R-multiple progress tracking
- Advisory HOLD, PROTECT, SCALE_AND_TRAIL, and EXIT states
- Breakeven guidance after qualifying 1R progress
- Scale and structure-trail guidance after qualifying 2R progress
- Playbook and market-state invalidation handling
- Target-reached tracking
- Immutable management-event history
- Mission Control integration

### Safety

The subsystem cannot submit, modify, replace, or cancel broker orders. It cannot move stops, change targets, or resize positions. Every recommendation is advisory and reports `production_effect: NONE`.

### New module

- `engine/adaptive_trade_management.py`

### New API routes

- `GET /api/trade-management/status`
- `POST /api/trade-management/evaluate`
- `POST /api/trade-management/record`
- `GET /api/trade-management/history`

### Database

- `adaptive_trade_management_events`

The unique `(trade_id, observed_at)` key makes repeated event recording idempotent and immutable.
