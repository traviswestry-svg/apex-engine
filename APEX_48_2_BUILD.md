# APEX 48.2.0 — Decision Evidence Pipeline

Connects immutable recommendation captures to the existing feature store and signal spine. Governed terminal ledger events create outcome labels; unresolved recommendations are never proxy-graded.

## New endpoints
- `GET /api/evidence-pipeline/readiness`
- `POST /api/evidence-pipeline/backfill?limit=500`

A safe startup backfill populates feature vectors and signal rows for existing recommendation-ledger captures. Integrity is returned as HTTP 200 while evidence is honestly accumulating; HTTP 503 is reserved for actual service/storage failure.
