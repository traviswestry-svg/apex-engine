# APEX 69.10.38 — Canonical Settlement Eligibility & Pending Evidence Classification Closure (candidate)

## Scope
Additive, read-only, database-wide eligibility and integrity diagnostic at `settle_pending_labels()` under `canonical_settlement_eligibility_38`. Existing `settle_labels()` and all label-write, broker, forecast, and trade-decision paths remain unchanged.

## Exact persisted cohorts
- Total feature / label / excursion / lifecycle records
- Feature-labelled and feature-unlabelled populations
- Excursion-backed labelled vs unlabelled samples
- Labels with no exact excursion (audit, do not assume corrupt)
- Pending feature IDs with lifecycle but no excursion
- Pending feature IDs without lifecycle or excursion
- Orphan excursion / label / lifecycle IDs without feature owner
- Pending lifecycle state/reason counts and bounded anomalous examples

All joins are exact `sample_id`; no timestamps, fuzzy keys, historical backfill, synthetic P/L, or data writes. The output explicitly distinguishes database-wide totals from scheduler's bounded settlement window (e.g. 3,401 unlabelled features vs 3,311 checked).

## Validation
- `python -m pytest -q tests/test_apex_69_10_38_settlement_eligibility.py`
- The read-only diagnostic runs once per `settle_pending_labels()` invocation. Its own errors do not block settlement.
- Verify production database counts against previously observed 29,123 features, 25,722 labels, 25,717 excursions, 15,620 lifecycle rows. These are historical comparison values, **not** hard-coded expectations.

## Release governance
The supplied repository already includes an unrelated **69.10.38 Gamma Model Integrity & Regime Stability** candidate and notes warning against promotion. Accordingly this is a **candidate settlement patch** and does not change manifest, capability registry, deployment version, or DB schema. Resolve the competing 69.10.38 scope and run full CI before a coordinated version bump. Do not claim deployed or production-ready.
