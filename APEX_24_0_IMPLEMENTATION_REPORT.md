# APEX 24.0 — Institutional Execution Intelligence

Release identity: `17.0.0_INSTITUTIONAL_EXECUTION_INTELLIGENCE`

## Implemented

- Advisory-only dynamic execution score and grade.
- Entry quality, chase risk, and slippage-risk analysis.
- TP1, TP2, TP3, breakeven, stop, and maximum-hold guidance.
- Explicit lifecycle state machine: IDEA, APPROVED, ENTERED, MANAGING, PROTECTED, EXITED, CANCELLED.
- Human confirmation required before ENTERED state.
- Append-only lifecycle event journal with integrity hashes.
- Point-in-time ordered execution replay.
- Mission Control 2.0 execution-intelligence summary and drill-down.
- Read-only journal and replay APIs.

## Safety

The module cannot place orders, modify orders, move stops, change risk limits, or bypass kill switches. All execution guidance remains advisory and human-confirmed.
