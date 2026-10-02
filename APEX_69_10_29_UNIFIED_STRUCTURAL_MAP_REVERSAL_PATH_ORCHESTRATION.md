# APEX 69.10.29 — Unified Structural Map & Reversal Path Orchestration

## Objective
Consolidate intelligence APEX already owns into one read-only operator map instead of creating another indicator stack. The build composes the Expected Session Range, 69.10.26 extension/reversal state, existing canonical market levels, strike magnets, and existing range targets into four surfaces: Regime Pivot, Reaction Zones, Destination Magnets, and Session Path Scenarios.

## What changed
- Added `engine/structural_map_orchestration.py`.
- Range Intelligence now emits `unified_structural_map`.
- The Regime Pivot is selected from an existing canonical APEX level only; the orchestration layer never synthesizes a mystery price.
- Upper/lower Reaction Zones combine the canonical Expected Session Range boundary, existing immediate reaction zone, and the 10/20/30% 69.10.26 extensions. They are explicitly search zones, not entry signals.
- Destination Magnets rank existing VWAP/POC/value/range/wall/strike-magnet references for the currently confirmed reversal direction. The orchestration score is ranking metadata only, not a probability.
- Session Path Scenarios separate upper rejection, lower rejection, and outside-range acceptance/continuation so APEX does not force a reversal while price is still accepted outside the envelope.
- Price-history dwell timing attached by 69.10.26 is propagated into the unified reversal path.

## Governance
This release is advisory orchestration only. It creates no trade authorization, no broker mutation, no automatic order submission, no new empirical probability, no synthetic market level, and no change to execution authority. Existing LTPE and historical-calibration evidence policies remain authoritative.
