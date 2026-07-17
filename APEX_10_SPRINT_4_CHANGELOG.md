# APEX 10 Sprint 4 — Phase 6 Historical Similarity

## Added
- `engine/historical_similarity.py`
  - explainable mixed categorical/numeric similarity scoring
  - robust numeric scaling using median absolute deviation
  - strict point-in-time candidate filtering
  - prior-session isolation by default
  - matched-neighbour outcome evidence with Wilson intervals
  - evidence-rate suppression below the established sample threshold
- `engine/similarity_routes.py`
  - `GET /api/similarity/<sample_id>`
  - supports `top_k` and `min_score`
- `feature_store_db.load_similarity_candidates()`
  - only decisions before the query timestamp
  - only labels settled by the query timestamp
  - no outcomes enter similarity-distance computation
- `tests/test_historical_similarity.py`

## Guardrails
- Similarity is descriptive evidence, not a trade signal.
- Labels and outcomes are excluded from distance calculation.
- Same-session examples are excluded by default.
- Future or not-yet-settled outcomes are structurally unavailable.
- Outcome rates are withheld for fewer than 50 matched labelled observations.
- Feature weights are explicit and versioned; new feature-store fields do not silently alter matching.

## Validation
- 579 tests passed.
