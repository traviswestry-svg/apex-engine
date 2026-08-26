# APEX 69.4.3 — Storage Observability Fix

## Purpose
Expose the existing governed storage-retention audit from inside the production Render process where `/data` is mounted, without requiring Render Shell access.

## Runtime endpoint
`GET /api/admin/storage/audit`

The route is covered by the existing application-wide APEX authentication layer. It executes only `engine.storage_retention.audit()` and is explicitly read-only.

## Preserved guardrails
- No automatic deletion.
- No automatic VACUUM.
- No WAL checkpoint from the endpoint.
- No price-sample pruning from the endpoint.
- No quarantine-file cleanup from the endpoint.
- Canonical decisions, grades, feature vectors, excursions, calibration evidence, and active databases remain preserved.
- Semantic release identity remains `69.4.3` (three numeric segments).

## Operational use
Use the authenticated endpoint to obtain live `/data` inventory, evidence-pipeline table sizing when available, retention eligibility metadata, and estimated quarantine reclaimability. Maintenance remains a separate explicit operator action.
