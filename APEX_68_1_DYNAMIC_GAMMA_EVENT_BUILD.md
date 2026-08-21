# APEX 68.1 — Dynamic Gamma & Event-Phase Build

## Scope
- Dynamic gamma-path versioning and freshness metadata.
- Multi-expiration gamma term structure and divergence/fragility state.
- Canonical intraday event phases for scheduled high-impact releases.
- Flow-excitation burst segmentation across release/price-discovery boundaries.
- Dynamic-state dashboard aggregation for gamma-path metadata and term structure.
- Reuses existing HLCE `level_outcomes` persistence; no duplicate outcome ledger added.

## Validation
Focused regression suite: 19 passed.

## Changed files
- engine/gamma.py
- engine/event_calendar.py
- engine/flow_excitation.py
- engine/dynamic_state.py
- tests/test_apex_68_dynamic_gamma_event.py
