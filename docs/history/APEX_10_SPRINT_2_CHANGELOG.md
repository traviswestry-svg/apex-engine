# APEX 10 Sprint 2 — Event Regime Engine

## Scope
Phase 4 from the July 17, 2026 SPX 0DTE system-design brief.

## Added
- Event-specific intraday states:
  - `NORMAL_SESSION`
  - `EVENT_PRE_RELEASE`
  - `EVENT_IMPULSE`
  - `EVENT_DISCOVERY`
  - `POST_EVENT_NORMALIZATION`
- Separate CPI, NFP, FOMC, and PPI profiles.
- Event-specific release times, confidence multipliers, slippage multipliers,
  flow-velocity expectations, and gamma-reliability multipliers.
- Leakage-safe normal-baseline eligibility controls.
- Expected-move decomposition into observed move, normal baseline, and
  incremental scheduled-event premium.
- Honest unavailable state when a normal-session baseline is missing.

## Integration
- `event_calendar` now returns `intraday_event_regime` while retaining the
  backward-compatible day-level `event_regime`.
- Decision Intelligence uses event phase instead of treating the full day as
  one undifferentiated event state.
- Premium Strategy blocks pre-release, impulse, and discovery structures until
  event-specific confirmation is available.
- Event confidence is multiplicative; event context never adds confidence.

## Validation
- 568 tests passed.
