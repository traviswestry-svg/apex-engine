# APEX 10 Sprint 1 — Phase 3 + Phase 3.5

## Phase 3: Quality-Gated Analytics

- Added one canonical `ALLOW / CAP / SUPPRESS` policy for chain-dependent analytics.
- Quality is multiplicative only; it is never an additive bullish/bearish term.
- Missing or low-confidence quality suppresses chain-dependent fields.
- Failed-but-measurable quality caps confidence contribution at 0.35.
- Contract recommendations hard-stop unless the chain gate passes.
- Canonical market state carries chain-quality lineage and suppresses/caps gamma fields when quality is supplied.

## Phase 3.5: Data Provenance & Decision Replay

- Added immutable SQLite decision snapshots keyed by `sample_id`.
- Snapshots contain raw cluster input, normalized replay frame, quality assessments,
  feature vector, decision output, and model/schema versions.
- Canonical JSON and SHA-256 hashes provide deterministic integrity checks.
- First-write-wins prevents later state from rewriting the historical decision.
- Added read-only `/api/provenance/<sample_id>` endpoint.
- Added replay verification helper that detects any regenerated-state mismatch.

## Validation

- Full suite: 562 tests passed.
