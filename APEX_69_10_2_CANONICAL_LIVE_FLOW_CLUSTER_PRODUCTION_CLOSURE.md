# APEX 69.10.2 — Canonical Live Flow Cluster Production Closure

## Purpose

69.10.2 closes the production stall identified by 69.10.1 scanner lifecycle telemetry: live flow-learning cycles were running during `MARKET_OPEN`, the upstream order-flow surface reported `OK`, yet `source_clusters`, writer invocations, and excursion capture all remained zero.

## Root cause

The canonical QuantData Order Flow Consolidated contract returns `tradeTime` as a Unix epoch-millisecond integer. The existing APEX flow-tape adapter treated long values as strings and truncated them to eight characters. The resulting value was not a valid `HH:MM:SS` timestamp. The classifier retained the event, but `engine.flow_clusters` correctly refused to position an untimed event in a cluster. With all live events unclusterable, `engine.flow_pl_pipeline` returned zero canonical `source_clusters`.

The current QuantData response vocabulary also uses `ASK`, `BID`, and `MID_MARKET`; APEX retained compatibility with older `AT_ASK`, `AT_BID`, and `MID` values but did not recognize the current vocabulary everywhere in the canonical flow path.

## Changes

1. `engine.flow_tape` now converts provider epoch-millisecond `tradeTime` to `HH:MM:SS` in `America/New_York`.
2. ISO timestamps and historical `HH:MM:SS` replay values remain supported.
3. Invalid timestamps remain `None`; APEX no longer substitutes the current clock. This prevents synthetic temporal proximity and false clustering.
4. `engine.flow_tape` and `engine.flow_classifier` now recognize current QuantData side values (`ASK`, `BID`, `MID_MARKET`) while preserving legacy aliases.
5. `engine.flow_pl_pipeline` now publishes stage diagnostics: raw rows, normalized rows, classified events, canonical clusters, singletons, unclusterable events, duplicate count, invalid timestamps, and a deterministic reason.
6. Scanner-owned `flow_learning_runtime` carries these stage counts and exposes exact zero-cluster states.

## Guardrails preserved

- No duplicate cluster engine.
- No cluster qualification relaxation.
- No invented timestamps.
- No synthetic excursions or P/L.
- No historical excursion backfill.
- No settlement or grading threshold changes.
- No automatic calibration activation.
- No behavioral authority.
- No execution authority.

## Expected production progression

On the first live session after deployment, valid QuantData rows should produce:

`raw_flow_rows > 0 -> normalized_flow_rows > 0 -> classified_flow_events > 0 -> source_clusters > 0 -> writer_invocations > 0`

Once a cluster is sealed and a contemporaneous mark exists:

`feature_rows_written > 0 -> capture_attempts > 0 -> excursions_inserted/updated > 0`

After normal maturity/settlement:

`canonical_excursion_rows_found > 0 -> labelled > 0 -> flow_features.graded > 0`

The pre-existing historical orphan vectors remain pending; 69.10.2 does not manufacture missing decision-time excursion evidence for them.
