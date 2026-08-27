# APEX 69.5.0 — Multi-Horizon Tick Momentum Intelligence

## Purpose
Adds an observational ES/MES transaction-momentum subsystem aligned with the standalone APEX ES Pine indicator vocabulary.

## Canonical horizons
- 233 transactions — FAST impulse
- 512 transactions — ENTRY confirmation
- 1000 transactions — STRUCTURE
- 2000 transactions — TREND

Each completed bucket is scored from body direction, uptick/downtick transaction-size pressure, and bucket-close trend relative to a synthetic bucket EMA. Horizon states are `BULL`, `BEAR`, or `NEUTRAL`; weighted alignment is -8..+8 using 1/2/2/3 weights.

## Evidence contract
Only genuine individual ES/MES transaction records with timestamp, price, and positive size are accepted. Aggregate OHLC/timeframe bars are explicitly rejected as tick evidence. Tick momentum is not L2/MBO depth and must never be represented as DOM, resting-liquidity, iceberg, or synthetic-depth evidence.

A licensed market-microstructure observation carrying genuine timestamped trades may mirror those trades fail-soft into this separate subsystem. No evidence stores are merged.

## Production posture
- observational only
- `production_effect = NONE`
- decision authority = NONE
- execution authority = NONE
- automatic promotion = false
- human promotion required before any future decision influence
- no trade-decision/confidence/execution change in 69.5.0

## Persistence
Bounded completed-bucket snapshots and current aggregator state use the canonical `engine.persistence` SQLite connection policy. Raw transaction history is not retained by this subsystem.

## Pine relationship
APEX and the standalone ES Pine indicator share horizon names, states, weights, and alignment vocabulary. Pine scripts do not directly share arbitrary variables with APEX; this build does not claim a server-to-Pine bridge or tick-chart alert capability.

## Versioned chart companion
`docs/APEX_ES_Tick_Momentum_v1_3.pine` carries the same 233/512/1000/2000 horizon vocabulary for visual ES confirmation. It is a separate indicator and does not grant APEX or Pine execution authority.
