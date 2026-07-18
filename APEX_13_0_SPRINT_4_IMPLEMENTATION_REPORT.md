# APEX 13.0 Sprint 4 — Similarity Intelligence Foundation

## Baseline
Built only from `APEX_13_0_Sprint_3_complete_repository.zip` extracted into a fresh workspace.

## Implemented
- Evidence-backed institutional feature-vector engine.
- Explicit feature schema `apex.institutional.features.v1` with categorical and normalized numeric fields.
- Deterministic SHA-256 feature hashing and immutable one-vector-per-recommendation storage.
- Idempotent SQLite migration and indexes for observation time, feature version, and hash.
- Nearest-neighbor similarity search with weighted mixed-feature comparison and factor explanations.
- Strict look-ahead protection: candidates must be observed before the source vector and caller cutoffs cannot extend beyond the source observation.
- Legacy research API compatibility while preferring institutional vectors when available.
- Honest `COLLECTING`, `READY`, `DEGRADED`, `UNAVAILABLE`, and `INSUFFICIENT_HISTORY` states.
- Outcome analytics remain disabled; similarity is descriptive research only.
- Institutional Similarity Research Lab dashboard.

## Feature coverage
The v1 schema includes market state/regime, strategy, direction, auction state, value relationship, profile shape, gamma regime, flow bias, breadth bias, trading mode, consensus grade, conviction grade, liquidity grade, risk state, confidence, consensus percentage, conviction score, execution score, position-quality score, readiness score, and expected-move utilization.

## APIs
- `GET /api/research/vector?recommendation_id=<id>`
- `POST /api/research/vector/<recommendation_id>`
- `GET /api/research/vector/<vector-or-recommendation-id>`
- `POST /api/research/vectors/build`
- `GET /api/research/features`
- `GET /api/research/schema`
- `GET /api/research/institutional-similarity/<id>`
- `GET /api/research/institutional-status`
- Existing `GET /api/research/similarity` and `GET /api/research/similarity/<id>` now support institutional vectors without breaking legacy vectors.
- `GET /apex_os/institutional_similarity`

## Safety
- No provider calls.
- No mock market data in production paths.
- No outcome, win-rate, expectancy, or probability claims.
- No live-trading or recommendation changes.
- Feature vectors are immutable and source-linked to evidence package hashes.
- Different feature versions are never compared.
