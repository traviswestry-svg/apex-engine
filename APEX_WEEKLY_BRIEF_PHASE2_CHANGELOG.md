# APEX Weekly Brief Phase 2 — Live Post-Cluster Confirmation

## Added
- `engine/flow_confirmation.py`
  - Thread-safe live observation tracker keyed by stable cluster ID.
  - SPX response at 30 seconds and 2 minutes.
  - ES confirmation at 2 minutes.
  - Signed-delta persistence only when provider delta is measurable.
  - Liquidity response only when an explicit liquidity score is available.
  - Future observations remain separate from the immutable decision-time vector.

## Updated
- `engine/flow_tape.py`: preserves optional provider delta, bid, and ask.
- `engine/flow_classifier.py`: carries observable delta and quote-at-trade fields without inference.
- `engine/flow_clusters_routes.py`: feeds canonical market-state observations into the tracker on each poll and returns enriched authenticity state.

## Confirmation rules
- Scheduled/automated candidates remain pending until at least three confirmation dimensions are measurable.
- Missing delta, ES, or liquidity remains `None`; no proxy is relabelled as the missing metric.
- Directional confidence continues to use a multiplier, never an additive quality term.

## Validation
- 556 tests passed.
