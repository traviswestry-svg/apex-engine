# APEX 11.0E — Durable Recommendation Memory

## Added

- Immutable `recommendation_ledger` decision-time store.
- Automatic capture from the authoritative premium-strategy composition/dispatch path.
- Idempotency keyed by session, strategy, expiration, legs, and decision epoch.
- Chain-priced economics, exact leg quotes, chain grade, quote age, evidence, probability, confirmation, provenance, and feature hash capture.
- Append-only lifecycle event stream for activation, quote snapshots, fills, close, settlement, invalidation, and grading.
- Honest calibration-readiness gate that remains `INSUFFICIENT_HISTORY` until enough terminal executable outcomes exist.
- Functional Operations Center checks for ledger writeability, capture coverage, and outcome readiness.

## New API routes

- `GET /api/recommendation-ledger`
- `GET /api/recommendation-ledger/recommendations`
- `GET /api/recommendation-ledger/latest`
- `GET /api/recommendation-ledger/recommendations/<recommendation_id>`
- `GET /api/recommendation-ledger/counts`
- `GET /api/recommendation-ledger/coverage`
- `GET /api/recommendation-ledger/health`
- `GET /api/recommendation-ledger/unresolved`
- `GET /api/recommendation-ledger/pending-grades`
- `POST /api/recommendation-ledger/record`
- `POST /api/recommendation-ledger/<recommendation_id>/activate`
- `POST /api/recommendation-ledger/<recommendation_id>/quote-snapshot`
- `POST /api/recommendation-ledger/<recommendation_id>/fill`
- `POST /api/recommendation-ledger/<recommendation_id>/close`
- `POST /api/recommendation-ledger/<recommendation_id>/settle`
- `POST /api/recommendation-ledger/<recommendation_id>/invalidate`
- `GET /api/recommendation-ledger/<recommendation_id>/timeline`
- `POST /api/recommendation-ledger/grade-due`
- `GET /api/calibration/readiness`

## Safety behavior

- No recommendation is graded from SPX direction alone.
- `grade-due` remains in `AWAITING_EXECUTABLE_OUTCOMES` until close or settlement economics are recorded.
- Lifecycle updates never overwrite the immutable original snapshot.
- Ledger failure is non-fatal to the live recommendation path but is surfaced in the Operations Center.

## Validation

- Python compilation passed.
- Complete suite: **675 passed, 0 failed**.
