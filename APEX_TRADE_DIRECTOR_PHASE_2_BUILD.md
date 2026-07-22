# APEX Trade Director — Phase 2

## Added
- One synthesized post-entry recommendation from APEX's cached institutional engines.
- Institutional Analysis panel covering Order Flow, Auction, Volume Profile, Dealer/Gamma, Market Structure, Expected Path, and Risk.
- Per-engine SUPPORTS / OPPOSES / NEUTRAL / UNAVAILABLE verdicts.
- Consensus-aware HOLD, PROTECT PROFIT, TRIM 50%, and EXIT recommendations.
- Narrative explaining the recommended management action.

## Stability and safety
- Reads only from `STATE["last_result"]`; it does not make new provider calls.
- Adds no scanner, thread, scheduled process, or import-time workload.
- Missing engine readings are labeled unavailable and are never invented.
- Recommendations remain advisory; no broker order is sent.
