# APEX Weekly Research Brief Build — 2026-07-17

## Implemented in this build

### Flow Authenticity Layer, Phase 1
- Detects clusters within a configurable 20-second window of each hour or half-hour.
- Requires predominantly complex-order evidence before applying the clock-synchronization penalty.
- Labels qualifying clusters `SCHEDULED_AUTOMATED_FLOW_PENDING_CONFIRMATION` rather than directional conviction.
- Applies a multiplicative directional-confidence adjustment; quality/authenticity never adds confidence.
- Supports future confirmation inputs:
  - `flow_persistence_30s`
  - `flow_persistence_2m`
  - `price_response_after_cluster`
  - `es_confirmation`
  - `liquidity_response`
- Requires at least three measurable confirmations before a scheduled burst can be restored to confirmed directional status.
- Persists safe pre-decision authenticity fields in the feature store.

## Deliberately not fabricated
The current flow feed does not yet provide future SPX/ES, liquidity, or signed-delta observations at the cluster level. Those fields remain `None` and the cluster stays pending until a later pipeline supplies them.

## Validation
- 552 tests passed.
