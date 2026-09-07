# APEX 11.1 — Institutional Execution OS

## Added
- History-free execution-quality engine with liquidity, quote freshness, spread, risk and operational scoring.
- Position Quality score independent of directional confidence.
- Deterministic fill simulator: best, expected and worst fill, slippage, fill probability and time-to-fill estimate.
- Institutional checklist with fail-closed blockers.
- Morning Readiness Score and derived Trading Mode.
- Execution and Readiness dashboard pages.
- Read-only execution/readiness REST endpoints.

## Important semantics
- Fill probability is an execution-condition heuristic, not a historically calibrated probability.
- Morning Readiness reports ANALYSIS_ONLY while the market is closed.
- No historical performance statistics are fabricated.
