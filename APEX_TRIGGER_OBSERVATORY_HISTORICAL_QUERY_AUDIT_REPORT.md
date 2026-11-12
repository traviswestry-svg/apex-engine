# APEX Trigger Observatory Historical-Query Memory Audit

**Base:** `apex-engine-main(20261112-221036).zip` (Stage 1 and Stage 2 deployed source), APEX 69.10.47.

## Confirmed source findings

- `engine/trigger_observatory.py:predictive_validation()` executes `SELECT ... FROM observed_trade_triggers WHERE symbol=? ORDER BY triggered_at`, then `.fetchall()` and allocates a list of dictionaries for every matching historical trigger. No date/row limit exists.
- `_attach_window_metrics()` performs exact-ID batches (Stage 2) but retains dictionaries for all linked price-observation rows in `by_trigger`. `_window_metrics` references per-trigger observation arrays again. Exact joins are correct; materialization is still potentially large.
- `predictive_validation` invokes `initialize_store(resolved)` without `reconcile=False`; that function uses writable `canonical_connect` and, by default, `_reconcile_window_integrity_conn()` which loads all historical triggers and all their observations, then executes updates. **This is the most important code-path discovery:** a nominally read-only report can do full-history write reconciliation before the reporting query. This audit does NOT change that behavior until parity and schema-migration tests are prepared.
- Stage 2's exact-identity decision metadata and trigger-observation query changes are present. Do not revert them or introduce fuzzy identity joins.

## Deliverable

`engine/trigger_observatory_historical_query_audit.py` is an explicitly operator-run, read-only SQLite audit. It reads aggregate row counts, distinct canonical links, total linked observations, top-five observation fan-outs, and SQLite query plans. It does not call `initialize_store`, return historical payloads, modify schemas, or run in the scanner or `/health`. Each substantive aggregate query has a 3-second query progress budget. Results can report `PARTIAL_BOUNDED` if the limit is reached.

## Operational use

```bash
python -m engine.trigger_observatory_historical_query_audit --db /data/apex_trigger_observatory.db --output trigger_query_audit.json
```

This report is a candidate. Run full CI and use a copy of the production database if practical. SQL aggregates may cause disk IO despite being read-only.

## Next fix gate

Before turning off reconciliation or changing query pagination, compare observable results for exact same historical database: predictive-validation row counts, window metrics, classification counts, all summary and cohorts, and canonical identity linkage. Then add compatibility tests for migrations, overdue observation reconciliation, and current scanner entrypoints. **Stage 3 storage work remains deferred.**
