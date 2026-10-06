# APEX 69.10.36 Build Report

## Release

**Version:** 69.10.36  
**Build:** Canonical Feature Lifecycle & Excursion Ownership Convergence  
**Database schema:** 8 (additive runtime table; no destructive migration)  
**Starting point:** user-supplied production 69.10.35 repository snapshot dated 2026-10-06.

## Production Evidence Driving This Build

69.10.35 proved that settlement selection and excursion ownership remained disjoint on fresh production data: settlement-requested feature samples could be registered and remain without exact excursions while a separate population owned persisted excursions. The settlement guardrail correctly refused to borrow or reconstruct evidence.

The source audit found the concrete convergence gap: `flow_pl_tracking` stores event contract facts only when an event is already markable. `reobserve_bound_feature_origins()` later joined canonical origin bindings to that table. A canonical feature could therefore persist, register, and bind its origin event IDs while its event had no initial mark; the exact owner existed, but the later re-observation path lacked durable contract facts for that owner.

## Architecture Added

1. `flow_feature_origin_event_facts` — additive table storing observable contract facts at the exact canonical feature-origin binding boundary.
2. `register_sample_identity(..., origin_event_facts=...)` — atomically persists those facts with the already-authoritative sample/event binding. Facts never select an owner.
3. Flow P/L source handoff now carries private `_origin_event_facts` for every member event, including currently unmarkable events.
4. Feature persistence forwards those facts only after the exact feature sample exists.
5. Durable bound-origin re-observation now uses canonical origin facts first and legacy `flow_pl_tracking` facts only as a compatibility fallback for older bindings.
6. `feature_lifecycle_excursion_convergence_health()` reports registered, bound, fact-bearing, excursion-bearing, and converged exact canonical samples.
7. The convergence health surface is included under sample-excursion health/evidence lifecycle telemetry.

## Canonical Invariant

For every newly captured settlement-eligible observational feature:

`feature_sample_id == lifecycle.sample_id == excursion_owner.sample_id`

This equality is established before settlement selection. Settlement remains exact-ID only.

## Guardrails Preserved

No fuzzy matching, nearest-time matching, reconstructed identities, historical backfill, synthetic excursion/P&L, cross-sample borrowing, relaxed settlement eligibility, automatic promotion, broker mutation, or execution authority was introduced.

The release remains observational. Current option-chain marks are used only to measure theoretical observational excursion for the already-bound exact feature owner.

## Database Changes

Additive table in the existing canonical tracking database:

`flow_feature_origin_event_facts(event_id PRIMARY KEY, sample_id, session_date, ticker, contract_type, strike, expiration, position_side, contracts, multiplier, entry_time_et, entry_mark, captured_at)`

Index: `idx_ffoef_session(session_date, sample_id)`.

No database schema-version bump is required; `init_db()` creates the table/index idempotently. No historical rows are backfilled.

## Validation

- New 69.10.36 tests: **3 passed**.
- Full `tests/test_apex_69_10_*.py` lineage: **219 passed**.
- Relevant feature-store / flow-P&L / excursion / settlement / identity suites excluding Flask-dependent `test_feature_store_api.py`: **311 passed**.
- Modified runtime module compile check: **passed**.
- Broader collection including `test_feature_store_api.py` is blocked in this build environment by missing `flask` (`ModuleNotFoundError`), not by an asserted APEX product-code failure.

## Production Acceptance

For new post-69.10.36 observations, verify:

- `samples_with_durable_origin_facts > 0`;
- `bound_without_durable_facts` trends to 0 for newly created samples;
- exact canonical re-observation writes excursions to the same registered sample IDs;
- `REQUESTED_AND_EXCURSION > 0` after samples mature;
- `REQUESTED_NO_EXCURSION` contains only genuinely not-yet-markable/not-yet-mature observations;
- ownership/readback integrity failures remain 0;
- no historical cohort is reconstructed.

## Behavioral Authority

**No direct trade-decision or execution authority added.** 69.10.36 changes observational evidence continuity only.
