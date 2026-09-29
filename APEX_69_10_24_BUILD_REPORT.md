# APEX 69.10.24 Build Report

## Release
- Version: **69.10.24**
- Build: **Persisted Feature Origin Identity Propagation Closure**
- Database schema version: **7**
- Starting point: attached production APEX 69.10.23 repository.

## Source audit and lifecycle trace
The 69.10.23 repository confirmed the following production path:

1. Canonical sample IDs are created in `engine/feature_store_writer.py` from the sealed cluster decision boundary.
2. The feature row is persisted through `feature_store_db.write_features()`.
3. `_capture_exact_persisted_sample()` re-reads the exact row and registers `(sample_id, session_date, legacy_cluster_key, decision_time)` in `flow_sample_identity_map`.
4. Later scanner cycles rebuild flow clusters in `engine/flow_pl_pipeline.py`; therefore the original Python cluster dict is not a durable provenance carrier.
5. Genuine aggregate cluster P/L is first available in `run_flow_pl()` after `compute_cluster_pl()`.
6. 69.10.23 attempted ownership with `resolve_exact_sample_identity()` against the **later current tuple**, explaining why mutable direction/state changes could prevent resolution.
7. Canonical excursions are written by `record_sample_excursion(..., require_registered_owner=True)`.
8. Post-commit visibility is verified through `get_sample_excursions()`, the same exact-ID reader used by settlement.
9. Settlement in `feature_store_writer.settle_labels()` remains exact sample-ID only.

## Architectural decision
Because later runtime clusters are rebuilt, in-memory fields alone cannot carry provenance across cycles. 69.10.24 uses the existing stable originating `member_event_ids` as a deterministic transport key. Bindings are created only after exact feature persistence has been re-read and canonical identity registration succeeds.

This is not market-attribute matching: ticker, expiration, direction, and timestamp proximity are never used to recover origin ownership.

`register_sample_identity()` now accepts optional `origin_event_ids` and publishes their bindings in the same canonical-store transaction as identity verification. An event-ID conflict with another canonical sample rolls back and fails closed.

Later P/L processing requires all continuing event IDs to resolve to one identical original tuple. That tuple is then revalidated against `flow_sample_identity_map` before a canonical excursion write.

## Preservation of earlier closures
- 69.10.20 write/readback verification preserved.
- 69.10.22 `require_registered_owner=True` enforcement preserved.
- 69.10.23 `feature_pl_handoff` telemetry preserved with subsystem version 69.10.23.
- Settlement matching remains exact-ID only.
- No fuzzy/semantic matching or owner reconstruction added.

## Secondary feature-only-unregistered condition
The existing writer already retries identity registration when an exact persisted feature row is encountered again. 69.10.24 additionally makes canonical identity verification and origin-event publication atomic within the canonical evidence store. The feature-store write and identity-store publication are still separate transactions/modules, so a process failure in the narrow interval after feature commit but before registration cannot be proven impossible locally. No destructive rollback of an immutable feature row was introduced merely to improve telemetry.

## Tests
Executed locally:

- Dedicated `test_apex_69_10_24_persisted_feature_origin_identity_propagation_closure.py`: **7 passed**.
- Entire `tests/test_apex_69_10_*.py` lineage: **148 passed**.
- Relevant feature-store / flow-P/L / excursion / settlement / evidence-lifecycle / identity tests, excluding the Flask-dependent API module: **311 passed**.
- `python -m compileall` / `py_compile` for modified runtime modules: **passed**.
- `tests/test_feature_store_api.py`: **not run; collection blocked by environment dependency `ModuleNotFoundError: No module named 'flask'`**. This is reported separately and is not treated as a product-code failure.

## Dedicated proof coverage
The new tests prove:
- release truth and guardrails;
- immutable origin registration and resolution;
- `UNCERTAIN → BULLISH` ownership continuity;
- `UNCERTAIN → BEARISH` telemetry;
- no owner reconstruction when provenance is absent even if a current tuple resolves diagnostically;
- tuple mismatch fails closed;
- genuine P/L is required;
- exact write/readback remains healthy;
- conflicting event-origin publication fails closed.

## Remaining production-only uncertainty
Local tests cannot prove the proportion of new production P/L observations whose rebuilt clusters retain exactly the same event-ID membership after persistence. The new telemetry makes this measurable after deployment through `origin_provenance_present`, `origin_provenance_missing`, validation counters, direction-evolution counters, and origin-owned excursion counters.

Historical 69.10.23 pending samples without origin bindings are intentionally not backfilled and may remain pending.
