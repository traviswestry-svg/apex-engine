# APEX — Premarket Directional Evidence Agreement & Abstention Explainability

**Candidate status:** Targeted tests passed; full repository CI blocked at collection.
**Baseline:** November 2, 2026 full repository ZIP, with November 3 Canonical Forecast Selection & Directional Snapshot Status Reconciliation candidate reconciled on top. Canonical manifest remains **69.10.47**.

## Scope

- Extended existing `engine/premarket_directional_features.py` with a **read-only** `explain_shadow_agreement(snapshot)` report from *frozen* canonical snapshot evidence.
- The existing rule in `shadow_direction` is **unchanged**: all three signed, nonzero, verified ES-derived inputs (`overnight_es_return`, `overnight_vwap_displacement`, `premarket_gap`) must agree. Other two ES-based features and gamma are contextual only for this rule.
- New field `details[].agreement_explainability` is emitted through the existing archived research endpoint only where a supported frozen feature snapshot exists. Values, feature status, source, observation/ingestion times, and age are read from frozen rows; missing values and historic snapshots are not backfilled.
- Explicit reason codes: `REQUIRED_DIRECTIONAL_INPUT_UNAVAILABLE`, `REQUIRED_DIRECTIONAL_INPUT_ZERO`, `REQUIRED_DIRECTIONAL_INPUTS_CONFLICT`, `THREE_REQUIRED_INPUTS_UNANIMOUS`; fallback `REQUIRED_DIRECTIONAL_INPUT_INVALID`.
- Existing canonical-origin checks from the earlier reconciliation candidate remain in force. Preparation-origin records are explicitly flagged and do not borrow later revisions.
- The three required inputs are potentially **correlated**, not confirmed independent or probabilistically calibrated. `independence_verified=false`, `confidence_calibrated=false`.

## Changed files (relative to Nov 2 full repository)

- `engine/premarket_directional_features.py` — reconciled canonical read model plus new agreement explainability.
- `engine/evening_recap.py` — reconciled preparation exclusion in official eligibility from earlier candidate.
- `tests/test_canonical_forecast_selection_reconciliation_candidate.py` — prior candidate regression tests for integration.
- `tests/test_premarket_agreement_explainability_candidate.py` — new tests covering conflict with five usable features, unanimity, zero, missing/stale, immutable archive, unknown schema.

## Validation run

- Premarket plus canonical tests: **28 passed**.
- Premarket + selected gamma + consolidation guard: **56 passed**.
- Python compilation of relevant engine files: **passed**.
- Full repository pytest: **68 collection errors** (main blocker `ModuleNotFoundError: No module named 'flask'`), one skipped. This is NOT a fully passing CI result.
- Canonical manifest remains 69.10.47; no new env variables, routes, database schemas or execution permissions introduced.

## Production validation

1. Run complete CI with project dependencies installed, including Flask, plus release-truth and governance checks.
2. Staging: query `/api/research/premarket-directional-features?limit=10` and inspect `details[].agreement_explainability` for a new valid canonical snapshot.
3. Confirm existing `status` and `direction` are unchanged by the explainability addition.
4. Confirm `CANONICAL_ORIGIN_REQUIRES_REVIEW` for preparation-occupied historical records, with no directional interpretation promoted.
5. November 3's exact frozen numerical values are not in the supplied diagnostic JSON; this build does **not** claim which three required signals caused that day's abstention. Only a read of the actual frozen snapshot can establish that.

**No official forecast promotion, historic rewrite, synthetic evidence, or trading authority changes.**
