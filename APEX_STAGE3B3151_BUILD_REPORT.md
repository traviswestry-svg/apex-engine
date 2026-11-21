# APEX Stage 3B.3.15.1 — Historical Receipt Correlation Schema Compatibility

## Scope
Narrow patch of the existing Stage 3B.3.15 read-only verifier, **not a new DB migration or runtime feature**.

### Confirmed Render columns
- `decisions`: `decision_id`, `canonical_gamma_snapshot_id`, `observed_at`, `ticker` (and other columns).
- `gamma_observational_snapshots`: `canonical_gamma_snapshot_id`, `received_at`, `persisted_at`, `observed_at`, `ticker` (and other columns).
- `canonical_gamma_snapshot_id` is indexed on the gamma table, per the provided diagnostic.

### Changes
1. Add `observed_at` to the end of existing preferred decision timestamp aliases (`decision_time`, `created_at`, `timestamp`, `observed_at`). **This is a stored timestamp claim and is not independently proven to be the decision execution time.**
2. Existing `ticker` alias for symbol comparisons is retained; new tests ensure it actually works on both actual table layouts.
3. Report explicit `schema_capabilities.decision_timestamp_source`, `decision_symbol_source`, `gamma_symbol_source`, `decision_timestamp_is_attested_execution_time: false`, and `gates.decision_timestamp_semantics: UNVERIFIED`.
4. Preserve all exact canonical gamma ID matches, indexed lookups, resource budgets, timestamp validation, duplicate detection, read-only DB mode, no row exports, and `BLOCKED_RESEARCH_ONLY`.
5. Four new tests, **24 passing tests total** in the candidate fixture suite.

### Installation
Extract ZIP at the repository root, preserving folder structure. The two existing files under `scripts/` and `tests/` are intentionally **replaced**; the new workflow is added. Use a new branch `apex-stage3b3151-schema-compatibility`, push, PR against protected `main`, and run checks before merging.

### Render commands after merge/deploy

```bash
python -m unittest discover -s tests -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -v

python scripts/apex_stage3b315_gamma_receipt_provenance_correlation.py \
  --root /data \
  --stage3b314-report /tmp/apex-stage3b314-evidence-source-inventory.json \
  --max-files 250 \
  --max-depth 3 \
  --max-rows 10000 \
  --budget-seconds 30 \
  --output /tmp/apex-stage3b3151-gamma-receipt-correlation.json

python -m json.tool /tmp/apex-stage3b3151-gamma-receipt-correlation.json
```

The predecessor report is optional by default; if missing after deployment, the report marks it `MISSING_OR_INVALID`. A successful bounded run should print `BOUNDED_RECEIPT_CORRELATION_COMPLETED_NOT_ATTESTED`, **not runtime availability proof**.

### Remaining limitations
- `decisions.observed_at` might be processing/observation time rather than the actual decision execution time; semantics unverified until source writer code or independently recorded events establish meaning.
- `received_at` and `persisted_at` are first-party timestamps, not provider-attested availability.
- Separate SQLite connections are not a coordinated point-in-time snapshot.
- Producer identity, gamma runtime activation, and historical full replay remain unverified.
- Live Render historical data audit was not executed in this build environment.
- Production migration remains `BLOCKED_RESEARCH_ONLY`.
