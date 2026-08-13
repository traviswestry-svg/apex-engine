# APEX Trade Director Phase 7 — Adaptive Trade Management Intelligence

## Added
- Personalized management profile derived only from user-confirmed Phase 6 outcomes.
- Learned Trade Health bands for HOLD, TRIM, PROTECT, and EXIT risk.
- Recommendation calibration by action.
- CALL/PUT and session-segment performance summaries.
- Confidence caps based on sample maturity.
- Shadow mode below 30 confirmed outcomes; assistive advisory mode thereafter.
- New endpoint: `GET /api/position/learning/adaptive-profile`.

## Safety and stability
- Phase 7 never sends or modifies broker orders.
- It never weakens an existing defensive recommendation.
- The initial release is advisory; learned guidance is not automatically substituted for the core recommendation.
- No scanner, provider request, background thread, startup database connection, or import-time workload was added.
- Phase 6's lazy SQLite archive remains the only persistence dependency.
