# APEX Stage 3A.2 — SQLite Record-Size, Payload-Shape & Retention Dependency Audit

## Build status
**Incremental operator-run candidate; not deployed or production-certified.** Based on Stage 3A production results from November 17, 2026, and the November 12 APEX source baseline. This candidate contains a new diagnostic script and tests, **not** a replacement application or live database copies.

## Scope
Targets six named tables spanning four SQLite files:

- `apex_evidence_pipeline.db`: `decisions`, `decision_effectiveness_attribution`
- `apex_trigger_observatory.db`: `observed_trade_triggers`
- `apex_tracking.db`: `flow_features`, `gamma_observational_snapshots`
- `apex_calibration.db`: `level_transition_observations`

The tool opens SQLite connections with URI `mode=ro` and `PRAGMA query_only=ON`. It samples up to 16 rows per table (hard cap 32) by descending rowid, or a verified primary-key index for WITHOUT ROWID tables. It measures SQLite `length()` of up to six candidate fields per table (hard cap eight). It does **not fetch or output payload field values**. Reports `min_length`, `max_length`, `mean_length`, null counts and sampled total lengths; these figures **are not equivalent to physical row bytes**. Text `length()` counts characters, BLOB counts bytes; they must not be extrapolated as population-wide estimates. Without suitable columns/indexed access, the tool skips.

SQLite progress handlers enforce a per-table bounded step/wall-clock check (default 500ms, maximum 750ms) and overall between-table elapsed budget (default 8s, max 9s). These are cooperative limits, **not guaranteed hard I/O timeout limits**. No full-table `COUNT(*)`, `dbstat`, `VACUUM`, checkpoint, writes, retention or index mutations are performed.

The audit also outputs foreign-key declarations, domain-specific **review categories** for canonical decisions, historical triggers, feature provenance, gamma identity and calibration transitions. Optional `--repo-root .` scans at most 256 Python source files, up to 64KiB each, to list filenames containing the table names. These are **textual reference hints only**: neither active usage nor retention dependencies are confirmed. The tool also attempts **indexed timestamp earliest/latest dates only**, when a suitable leading-column index exists; these are not row-age distributions and do not authorize deletion.

## Local execution (once candidate files have been integrated into the deployed code)

```bash
python scripts/apex_stage3a2_record_audit.py \
  --root /data --repo-root . \
  --sample-rows 16 --sample-columns 6 \
  --query-budget-ms 500 --total-budget-ms 8000 \
  --output /tmp/apex-stage3a2-records.json
```

If performance impact is suspected, use `--sample-rows 4 --sample-columns 3 --query-budget-ms 250`. The output must remain outside the `/data` volume; the script refuses to write there. `/tmp` is not persistent; export externally if history is needed. Running as-is against the last uploaded *November 12 baseline repository* requires copying the script in this candidate to `scripts/` first.

## Non-negotiable limitations

1. **No production scan has been executed here**; there is no true observed row distribution or compression estimate.
2. Sample order is the highest rowid or primary key, not random, unbiased, or guaranteed newest by time.
3. Large `length()` operations can cause I/O and memory traffic. The progress handler cannot stop arbitrary blocking system calls.
4. No cross-database FK graph or canonical evidence ownership can be inferred from SQLite schema alone. The code-reference hints are not evidence of active dependencies. This tool does not verify backup or restore procedures.
5. Table allocation sizes (Stage 3A) and logical data-length samples (Stage 3A.2) are not mathematically additive or sufficient to estimate reclaimable space.
6. All retention categories are `NOT_ESTABLISHED`. Stage 3B deletion, compression, archival, index removal, pruning, WAL maintenance and VACUUM are **not approved**.

## Testing
- 12 new Stage 3A.2 tests: passed.
- 9 existing Stage 3A tests: passed.
- 26 selected APEX storage, retention, gamma, settlement and release-governance regression tests: passed.
- **Total: 47 selected tests passed.** Full CI and production validation pending.

## Expected output
`schema=apex.stage3a2_record_payload_retention_audit.v1` with `databases[].tables[].column_lengths`, `indexed_time_boundary`, and `dependency_review`. `retention_guardrails` asserts no records, schemas, canonical evidence, or trading authority are modified.
