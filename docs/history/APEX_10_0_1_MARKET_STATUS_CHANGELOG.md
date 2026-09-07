# APEX 10.0.1 — Market Status & Evidence Clarity

## Purpose
Improve after-hours interpretation without changing trading decisions, confidence math, quality-gate enforcement, or institutional bias.

## Changes

### Explicit after-hours data states
- Chain quality now displays `NO_LIVE_CHAIN` when the cash market is closed and no live chain assessment exists.
- The underlying quality-gate action remains preserved in evidence as `gate_action` (for example, `SUPPRESS`).
- Liquidity now displays `NOT_MEASURABLE_AFTER_HOURS` instead of generic `UNKNOWN` when live execution measurements are unavailable after hours.

### Mixed-evidence visibility
- Added `evidence_alignment` with:
  - `MIXED`
  - `BULLISH_ALIGNED`
  - `BEARISH_ALIGNED`
  - `NEUTRAL_OR_UNMEASURABLE`
- Institutional bias is not recomputed.
- When canonical bias and evidence are mixed, the story headline now states, for example: `Bearish bias · mixed evidence`.

### Market Status card
Added a consolidated dashboard strip covering:
- Cash Market
- ES Futures
- Options Chain
- Flow
- Replay
- Institutional State
- Trade Engine

### API additions
`/api/institutional_state` now includes:
- `market_status`
- `evidence_alignment`
- `market_state.evidence_alignment`
- explicit presentation states for after-hours quality and liquidity

## Guardrails retained
- No direction recomputation
- No change to quality-gate enforcement
- No automatic learning activation
- No fabricated institutional intent
- No similarity-driven trade decision

## Validation
- Focused institutional/API tests: 9 passed
- Full repository: 628 passed, 1 unrelated order-dependent range-intelligence test failed in the combined run
- The range-intelligence test passes when executed in isolation
