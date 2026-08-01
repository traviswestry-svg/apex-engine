# APEX 50.6.3 — Morning Brief Mobile Presentation & Narrative Resilience

## Objective
Repair the mobile Morning Brief presentation without changing trading, signal, risk, level-calibration, or execution behavior.

## Findings
The Execution OS Morning Readiness page had regressed to rendering the complete Morning Brief Markdown directly through `marked.parse()`. On a narrow mobile viewport this produced an oversized title, dense raw level text, `[FEED REQUIRED]` noise, and a raw Anthropic timeout exception prominently at the top of the brief. Earlier 50.3 mobile protections had also fallen out of the template.

## Changes
- Replaced the primary raw-Markdown Morning Brief display with a structured responsive renderer driven by the existing Morning Brief JSON payload.
- Added compact top metrics for SPX reference, expected move, gamma regime, and data quality.
- Embedded the LTPE upward next-level path directly into the Morning Brief via `/api/level-calibration/transitions/path?direction=UP&max_steps=6`.
- Added a concise institutional key-level table using canonical structured levels.
- Moved unavailable overnight / OR / IB values into a dedicated `Monday Live Levels — Awaiting Session Data` section.
- Added a compact trade-map section.
- Kept the full Markdown report and diagnostics available under a collapsed `Full report & diagnostics` disclosure.
- Sanitized AI narrative failures in the primary UI. Raw transport exceptions are no longer rendered as the main brief message.
- Restored provider/source chips and human-readable, color-coded gamma presentation from the earlier mobile presentation contract.
- Reduced the default AI narrative timeout from 18 seconds to 10 seconds. `APEX_BRIEF_AI_TIMEOUT_SECONDS` remains the environment override.
- Updated deterministic fallback Markdown so technical exception text remains in structured diagnostics (`narrative_error`) rather than the visible headline.

## Safety / Scope
- No trading logic changed.
- No signal logic changed.
- No risk or broker behavior changed.
- No LTPE probability policy changed.
- No market calculations changed.
- Existing Morning Brief and LTPE APIs remain backward compatible.

## Validation
- `71/71` APEX 65 + APEX 50.6 targeted regression tests passed.
- `22/22` focused Morning Brief mobile + LTPE regression tests passed.
- Repository-wide Python compile passed.
- Dashboard JavaScript syntax checks passed.
