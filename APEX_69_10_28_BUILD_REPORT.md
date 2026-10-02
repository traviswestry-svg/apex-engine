# APEX 69.10.28 — Canonical Forecast Decision-Time Provenance

## Objective
Bind the first eligible pre-open Morning Brief to an exact immutable canonical forecast identity and require that identity/integrity proof before Evening Recap grading.

## Closure
- Adds canonical `forecast_id` and SHA-256 `snapshot_hash` for the official Morning Brief.
- Freezes canonical structured forecast components at decision time without deriving missing values later.
- Adds additive archive columns for forecast identity/hash/component snapshot.
- Existing historical rows remain legacy/unverified; no retroactive identity is synthesized.
- Canonical official forecast rows are protected by an immutable database trigger.
- Evening Recap verifies session, ticker, forecast ID, and snapshot hash before grading.
- Removes same-process Morning Brief cache fallback from Evening Recap grading.
- Cached recaps are reused only when their forecast ID/hash exactly match the verified official forecast.
- Preserves first-eligible-preopen-only promotion and post-open revision rejection.
- Does not change trade decisions, position sizing, execution authority, historical-learning excursion ownership, or 69.10.27 durable origin re-observation behavior.

## Fail-closed states
- `CANONICAL_FORECAST_PROVENANCE_REQUIRED`
- `CANONICAL_FORECAST_IDENTITY_MISMATCH`
- `CANONICAL_FORECAST_INTEGRITY_FAILURE`

## Guardrails
No post-open promotion; no historical forecast rewriting; no free-text reconstruction; no nearest-time matching; no session-date-only fallback for canonical grading; no evening recomputation; no synthetic missing components; no legacy auto-promotion; no in-memory cache grading authority.

## Validation
- APEX 69.10.x focused/release suite: **176 passed**.
- Full repository suite cannot collect in this sandbox because Flask is not installed: **68 collection errors**, all observed as `ModuleNotFoundError: No module named 'flask'`.
- Python compilation for modified runtime modules passed.
