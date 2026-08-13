# APEX 24.4 — Multi-Timeframe Intelligence

Release identity: `17.4.0_MULTI_TIMEFRAME_INTELLIGENCE`

## Summary

A hierarchical market model over eight timeframes (Weekly, Daily, 4H, 1H, 15M,
5M, 3M, 1M) producing higher-timeframe bias, lower-timeframe confirmation, an
alignment score, trend agreement, conflict detection, and institutional
directional confidence. Deterministic and read-only / advisory.

## Implemented

- Weighted directional model with institutional weights (higher timeframes
  dominate bias) and tiered grouping (higher / intermediate / lower).
- `alignment`: dominant bias, alignment score, trend agreement %, per-tier bias,
  lower-timeframe confirmation, institutional directional confidence.
- `conflicts`: HTF_LTF_CONFLICT, NEUTRAL_HIGHER_TIMEFRAME, and per-timeframe
  disagreement detection.
- `integration_signals`: compact bias/confidence signal for consumption by the
  Trading Brain, Forecast Engine, Playbook Engine, Execution Intelligence, and
  Portfolio Intelligence (they read `last['multi_timeframe']` when populated).
- Robust alias parsing for timeframe keys (weekly/1W, daily/1D, 4H/H4, etc.).
- Mission Control: `MULTI_TIMEFRAME` panel + `/api/multi-timeframe/alignment`
  drill-down.

## API surface (one canonical namespace, net-new)

`GET /api/multi-timeframe/status`, `GET /api/multi-timeframe/alignment`,
`GET /api/multi-timeframe/conflicts`, plus supporting
`GET /api/multi-timeframe/integration` and POST variants of alignment/conflicts
for ad-hoc analysis. No pre-existing `/api/multi-timeframe/*` routes existed, so
there was no reconciliation.

## Integration note (accurate scope)

This release exposes the integration surface and the compact
`integration_signals` payload; the consuming engines read
`last['multi_timeframe']` when the scanner populates it. Deep in-engine wiring of
each consumer is intentionally not forced here to avoid regressions; the signal
contract and Mission Control surface are in place for consumers to adopt.

## Registrar hardening

Registration runs outside the broad non-fatal block, verifies all three
canonical routes, and fails loudly on missing or duplicate routes.

## Safety

Deterministic, read-only, advisory. No persistence, no broker effect, no
automatic execution.
