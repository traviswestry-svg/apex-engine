# APEX 10 Sprint 3 — Phase 5 Confidence Attribution

## Added
- `engine/confidence_attribution.py`
- Component-level weighted-point attribution for ICI
- Signed bullish/bearish engine contribution rows
- Multiplicative reliability adjustments for chain quality, flow authenticity, and event regimes
- Explicit missing-data handling
- Confidence attribution exposed in institutional decision output and Decision Intelligence

## Rules
- Quality never adds confidence.
- Chain quality modifies only gamma-derived confidence.
- Flow authenticity modifies only flow-derived confidence.
- Event phase modifies the final confidence score.
- Existing directional logic and reported decision confidence remain unchanged in this sprint.

## Validation
- 574 tests passed
- 0 failed
