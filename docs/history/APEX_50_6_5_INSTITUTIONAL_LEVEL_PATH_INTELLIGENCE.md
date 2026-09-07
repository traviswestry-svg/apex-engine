# APEX 50.6.5 — Institutional Level Path Intelligence

## Objective
Convert LTPE's raw ordered level ladder into a decision-grade institutional path. Nearby microstructure references are clustered into zones, major destinations are prioritized, useful intermediate staging levels are retained selectively, and impractical distant targets are pruned.

## Changes
- Added adaptive institutional zone formation around nearby levels.
- Added significance tiers: PRIMARY, SECONDARY, INTERMEDIATE, SUPPORTING.
- Supporting HVN/LVN/liquidity references are retained inside major zones instead of becoming separate path steps.
- Secondary references immediately ahead of a primary destination are absorbed into that destination zone.
- Intermediate levels are retained only when they materially divide a wide primary-to-primary auction span.
- Added expected-move-aware maximum path distance so far-tail levels such as an 8000 low-gamma strike do not appear as practical 0DTE destinations.
- Added zone-level evidence aggregation across member level types. No sample means no probability; the existing evidence-only policy remains unchanged.
- Added `path_mode=INSTITUTIONAL_ZONES`, `path_intelligence_version`, zone bounds, member count, significance tier, and supporting-zone metadata to the path payload.
- Updated Morning Readiness path cards to show zone/tier/reference metadata.

## Backward Compatibility
The legacy LTPE `version` field remains `50.6.2.2_LEVEL_TRANSITION_PROBABILITY` for clients/tests that depend on it. The new extension is identified separately by `path_intelligence_version=50.6.5_INSTITUTIONAL_LEVEL_PATH_INTELLIGENCE`.

## Validation
- 52/52 APEX 50.6 + APEX 65.6 regression tests passed.
- Dedicated 50.6.5 path clustering and no-fabrication tests passed.
- Repository Python compilation passed.
- Trading, signal, risk, broker, Morning Brief calculation, and Anthropic behavior unchanged.
