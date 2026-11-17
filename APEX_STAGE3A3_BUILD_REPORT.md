# APEX Stage 3A.3 — Bounded JSON Structural Redundancy & Lossless Compression Feasibility Audit

**Status:** Incremental candidate; locally tested; **not deployed to Render**.

## Intended use
Standalone operator-invoked, read-only investigation of known JSON columns identified in Stage 3A.2. Reports aggregate UTF-8 payload byte lengths, JSON shape counts, and optional in-memory lossless `zlib` level-6 compression feasibility. The audit makes **no** claims of recoverable SQLite filesystem bytes or production reader compatibility.

## Included files
- `scripts/apex_stage3a3_json_audit.py` — self-contained Python 3.10+ CLI; standard library only.
- `tests/test_apex_stage3a3_json_audit.py` — synthetic SQLite tests.
- `INTEGRATION_MANIFEST.json` — deployment and change boundaries.

## Exact target fields
- `apex_evidence_pipeline.db`: `decisions.snapshot_json`
- `apex_trigger_observatory.db`: `observed_trade_triggers.blocker_codes_json`, `.evidence_json`, `.etrade_handoff_json`, `.canonical_grade_json`
- `apex_tracking.db`: `flow_features.features_json`, `.availability_json`, `gamma_observational_snapshots.snapshot_json`, `.lineage_json`
- `apex_calibration.db`: `level_transition_observations.target_cluster_json`

## Recommended production invocation
From the Render service shell, **after merging and deploying the candidate, after full CI**, preferably in an off-market window:

```bash
python scripts/apex_stage3a3_json_audit.py \
  --root /data \
  --mode both \
  --sample-rows 16 \
  --max-chars 65536 \
  --raw-byte-budget 2097152 \
  --table-budget-ms 900 \
  --total-budget-ms 10000 \
  --output /tmp/apex-stage3a3-json-audit.json
cat /tmp/apex-stage3a3-json-audit.json
```

`--mode structure` omits compression; `--mode compression` omits structural analysis. Results contain statistics only; no raw payload values, hash values, JSON keys, IDs, or private shape signatures. Compression is performed in memory and discarded after each sample.

### Boundedness and operational notes
- Hard configured caps: 4 databases; 2 tables per DB; 4 columns/table; 16 most recent rowid records per column; up to 65,536 returned characters per value; 2 MiB of sampled UTF-8 data across the **entire** audit; 1,200 ms cooperative per-table query budget, 12,000 ms cooperative overall budget, and 20,000 progress-handler callbacks per query.
- Uses `mode=ro` URI and `PRAGMA query_only=ON`. Schema lookup and last-rowid access are the only queries. `WITHOUT ROWID` tables are skipped, as no verified bounded access path is assumed. A `substr` sentinel detects potentially truncated values; these are not parsed or compressed.
- **Cooperative limits are not hard CPU/I/O timeouts**. SQLite may read large source pages even when returned values are truncated. Run off-market; stop if health degrades.
- UTF-8 bytes sampled are not equivalent to SQLite page allocation, and sampled compression ratios do not predict DB compaction, disk savings, or compatibility. Shape comparison uses internal key names transiently but exports **no** keys/signatures/hashes; similar structures are not proof of duplicate content.
- This is an operator diagnostic only: no `/health` integration, scheduled task, background process, SQL write, checkpoint, vacuum, deletion, schema mutation, trade-authority change, or retention authorization.
- Before *any* later optimization, independently establish canonical evidence ownership, cross-DB reference semantics, reader compatibility, restore-tested external backups, and a rollback plan.

## Local testing
`pytest -q tests compat/tests`: **37 passed**. Includes 16 new Stage 3A.3 tests and 21 earlier Stage 3A/3A.2 tests. Full APEX repository CI not executed; no production data were accessed.

## Integration
Copy `scripts/apex_stage3a3_json_audit.py` and `tests/test_apex_stage3a3_json_audit.py` into corresponding repository paths. Run unit tests and full CI. Merge/deploy only after operator review. This package is an incremental patch, **not** a replacement APEX repository and **not** a production deployment.
