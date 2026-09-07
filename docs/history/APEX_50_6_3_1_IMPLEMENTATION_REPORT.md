# APEX 50.6.3.1 — Morning Readiness Mobile Polish

## Scope
Presentation-only refinement of the structured Morning Brief introduced in APEX 50.6.3.

## Changes
- Grouped Generate and Refresh controls into a compact mobile action cluster.
- Added accessible refresh label/title.
- Humanized `NEXT_SESSION_PREP` to `Next-Session Prep`.
- Shortened weekend session display to `Weekend Prep`.
- Replaced long archive text with compact status badges (`Official archived`, `Revision saved`, `Archive unavailable`).
- Compressed the operational status bar to brief mode, provider state, data quality, and latency.
- Reduced mobile narrative fallback padding/line height and provider-chip sizing.
- Preserved structured metrics, LTPE path, key levels, pending-session levels, trade map, and collapsible diagnostics.

## Behavior unchanged
- Morning Brief calculations and data sources.
- LTPE transition probabilities and evidence-only policy.
- Trading signals, risk controls, broker logic, and execution behavior.

## Validation
- 79/79 APEX 50.6 + APEX 65 regression tests passed.
- 15/15 focused Morning Brief/mobile tests passed.
- Inline dashboard JavaScript syntax checked after template substitution.
