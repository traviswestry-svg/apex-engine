# APEX 13.0 Sprint 2 — Institutional Data Quality Framework

Built directly on the APEX 13.0 Sprint 1 baseline. The implementation evaluates immutable evidence packages only and does not query providers or rewrite ledger history.

## Implemented
- Deterministic evidence-package quality scoring and A–F grades.
- Fail-closed research eligibility gate.
- Required snapshot checks for narrative, consensus, conviction, confidence attribution, execution, position quality, liquidity, provider health, and freshness.
- Evidence-integrity, stale-data, provider-failure, timeline-order, and duplicate-event checks.
- Append-only quality assessment records with deterministic hashes.
- Quality incident schema and indexes.
- Aggregate coverage, eligibility, grade, and defect reporting.
- Institutional Data Quality dashboard and APIs.

## Safety
Missing critical evidence forces exclusion. Stale data and provider failures are explicit defects. No values are synthesized. The recommendation ledger and Sprint 1 case files remain immutable.

## Versions
- Engine: 13.0.0-sprint2
- Schema: 1
- Policy: apex.data-quality.v1
