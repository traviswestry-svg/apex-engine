# APEX Stage 3B.3.15 — Historical Gamma Receipt & Decision Provenance Correlation

**Candidate / research only. Migration authority: `BLOCKED_RESEARCH_ONLY`.**

## Objective

Build upon Stage 3B.3.14 metadata inventory by checking historical *stored-record* correlations between `decisions.canonical_gamma_snapshot_id` and `gamma_observational_snapshots.canonical_gamma_snapshot_id`, including recorded `received_at`, `persisted_at`, and decision times. The scanner NEVER runs the historical trading engine or changes production data. Correlation does **not** attest actual historical provider availability or activation.

## Included files

- `scripts/apex_stage3b315_gamma_receipt_provenance_correlation.py`
- `tests/test_apex_stage3b315_gamma_receipt_provenance_correlation.py`
- `.github/workflows/apex-stage3b315-gamma-receipt-tests.yml`
- This report and `INTEGRATION_MANIFEST.json`

## Install

Extract the candidate ZIP at the root of the `apex-engine` working tree. Create branch `apex-stage3b315-gamma-receipt-correlation`, review code, commit and open a PR to protected `main`. Existing `ci.yml` is untouched. GitHub workflow runs synthetic tests, **not** the historical production audit.

## Render Shell — first verify tests

```bash
python -m unittest discover -s tests -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -v
```

## Render Shell — bounded real-data audit

Stage 3B.3.14's inventory report can be regenerated if `/tmp` is lost; it is optional for this audit (and its missing/invalid state is recorded). For strict chaining, supply it and `--require-previous`.

```bash
python scripts/apex_stage3b315_gamma_receipt_provenance_correlation.py \
  --root /data \
  --stage3b314-report /tmp/apex-stage3b314-evidence-source-inventory.json \
  --max-files 250 --max-depth 3 --max-rows 10000 \
  --budget-seconds 30 \
  --output /tmp/apex-stage3b315-gamma-receipt-correlation.json
python -m json.tool /tmp/apex-stage3b315-gamma-receipt-correlation.json
```

The script auto-discovers SQLite databases under `/data` that contain the exact `decisions` and `gamma_observational_snapshots` tables. If multiple databases match, it **fails closed**; supply explicit `--decision-db` and `--gamma-db` file paths, both under `/data`. It does not print paths. The gamma canonical-ID column must have a leading index to avoid unbounded table scans. If `SCHEMA_INCOMPATIBLE_FAIL_CLOSED` or `GAMMA_EXACT_ID_UNINDEXED_FAIL_CLOSED` occurs, inspect actual schema safely; do NOT create indexes on production databases or alter the schema to satisfy this audit.

For strict previous-report validation, add `--require-previous` to the command.

## Evidence logic

- Opens existing SQLite files with `mode=ro` and `PRAGMA query_only=ON`.
- Uses a bounded read of up to `max-rows + 1` decisions, and up to two gamma matches per exact ID; no latest-snapshot fallback or broad `LIKE` joins.
- Distinguishes missing IDs, absent snapshots, duplicates, missing/invalid timestamps, receipt-after-decision, persistence-after-decision, persistence-before-receipt, and optional symbol mismatches.
- Timezone-naive text timestamps are rejected as unverifiable (no guessed timezone). Epoch numeric timestamps are accepted in seconds.
- Tracks pre- and post-reference totals using **2026-09-18 13:45:00.256463 UTC**, a historical reference time only, **not a verified activation time**.
- Does not attempt to equate `decision_provenance.snapshot_id` with a gamma snapshot; its schema presence is an informational capability only. A future separately established semantic identity map is required before joining provenance.
- Does not inspect `scanner_events.boot_id` or `recommendation_ledger.commit_sha` because their relationship to each decision is not established. Producer origin is always `UNVERIFIED`.
- Returns aggregate counts only; never emits decisions, gamma IDs, symbols, individual event timestamps, DB locations, or log contents.
- Fails closed for ambiguous database selections, missing key columns, absent exact-ID index, and incomplete scans; output confined to `/tmp` outside `/data`.

## Interpretation

A `BOUNDED_RECEIPT_CORRELATION_COMPLETED_NOT_ATTESTED` result means the read-only bounded walk completed. It does **not** prove the scanned population was the entire historical population; check `counts.scanned` against previously reconciled totals. The `stored_receipt_and_persistence_predecision` gate can say `STORED_TIMESTAMP_CLAIMS_ONLY`: this remains first-party information, not independently attested provider availability. All independent runtime, origin, point-in-time, and replay gates stay `UNVERIFIED`.

Historical evidence does not justify production migration. No backfill, record reclassification, trade execution, cutover, or schema changes are authorized.
