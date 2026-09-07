# APEX Trade Director Phase 17 — Multi-Timeframe Intelligence

## Scope

Phase 17 adds a cached-only institutional timeframe hierarchy across:

- 1W
- 1D
- 4H
- 1H
- 15M
- 5M
- 1M

## Capabilities

- Normalizes partially structured timeframe snapshots.
- Infers direction from explicit bias/trend fields or EMA/VWAP structure when supplied.
- Produces weighted directional alignment and confidence scores.
- Separates higher-timeframe thesis from execution-timeframe bias.
- Detects timeframe conflicts and identifies the opposing frames.
- Determines entry timing as `ENTRY_WINDOW_OPEN`, `WAIT_FOR_TRIGGER`, or `AVOID_ENTRY`.
- Applies advisory Trade Health and sizing posture adjustments.
- Fails closed when there is insufficient cached coverage.

## Decision gates

- `ALIGNED`
- `WAIT_FOR_ALIGNMENT`
- `TIMEFRAME_CONFLICT`
- `DATA_LIMITED`
- `STAND_DOWN`

## API

- `GET /api/position/multi-timeframe-intelligence`
- `POST /api/position/multi-timeframe-intelligence`

The POST route accepts normalized timeframe data for deterministic evaluation without any provider call.

## Dashboard

A new Multi-Timeframe Intelligence panel displays:

- Alignment score
- Confidence and coverage
- Timeframe matrix
- Higher-timeframe thesis
- Execution-timeframe bias
- Entry timing
- Active conflicts
- Advisory health and sizing effect

## Safety and deployment

Phase 17:

- does not contact providers or brokers;
- does not start workers;
- does not add startup initialization;
- does not override Phase 9 risk limits;
- does not bypass Phase 10 confirmation;
- does not override Phase 14 `STAND_DOWN`;
- does not bypass Phase 16 execution controls.

No new environment variables are required.

## Validation

- Python compilation passed.
- Dashboard JavaScript syntax validation passed.
- Bullish alignment test passed.
- Higher/lower timeframe conflict test passed.
- Insufficient coverage test passed.
- `STAND_DOWN` authority test passed.
- Phase 13–16 regression tests passed.
- Active Trade Director regression tests passed.
- 49 tests passed.
