# APEX 13.0 Sprint 1 — Institutional Evidence Framework

Implemented immutable recommendation evidence packages, deterministic serialization and hashes, versioned snapshots, append-only evidence timelines, integrity validation, read-only evidence APIs, and a reusable Institutional Case File page.

## Safety
Evidence is built only from persisted Recommendation Ledger records. No market data, outcomes, performance, or provider state is fabricated. Missing recommendations return `UNAVAILABLE`; incomplete packages are marked `INCOMPLETE` and are not calibration-ready.

## Database
New additive SQLite database `apex_evidence.db` with idempotent schema initialization and indexes for package status, snapshots, timelines, and integrity checks. Existing ledger tables and rows are unchanged.

## Deployment
Commit all files, deploy through the existing Render pipeline, and optionally set `APEX_EVIDENCE_DB` to a persistent-disk path. Without persistent storage, Render filesystem resets can remove evidence records.

## Rollback
Deploy the prior release. The additive evidence database can remain in place because older code does not reference it. Do not delete Recommendation Ledger history.
