# APEX Stage 3B.3.12 — Historical Decision-Time Gamma Linkage & Runtime Evidence Verification

**Candidate only — not executed against APEX production data.** Migration authority stays `BLOCKED_RESEARCH_ONLY`.

## Contents
- `scripts/apex_stage3b312_linkage_runtime_verification.py` — recomputes or reviews bounded real-decision linkage findings and reconciles earlier semantic report. No trading execution, no database writes, no individual decision or snapshot export.
- `tests/test_apex_stage3b312_linkage_runtime_verification.py` — eight offline synthetic unit tests.
- `.github/workflows/apex-stage3b312-verification.yml` — optional GitHub Actions **unit-test-only** workflow; GitHub runner does **not** have the production databases.
- `evidence/stage3b311-validation.json` — **user-supplied** Stage 3B.3.11 passing fixture report for input, *not independent attestation*.

## Installation with GitHub Desktop
Unzip at the root of your `apex-engine` working copy, retaining paths. Create a new branch `apex-stage3b312-linkage-runtime-evidence`, inspect changes, commit, push, open PR. Do not overwrite existing Stage 3B.3.9 or 3B.3.10 scripts. The default APEX CI remains unchanged.

## First: GitHub synthetic unit tests
```bash
python -m unittest discover -s tests -p 'test_apex_stage3b312_linkage_runtime_verification.py' -v
```
The GitHub Actions workflow runs these same tests **only**. A green result here does not establish historical record linkage or runtime activation.

## Real historical correlation: read-only Render Shell
Prerequisites: existing `scripts/apex_stage3b310_origin_population_audit.py` and `scripts/apex_stage3b39_runtime_decision_gamma_audit.py` from previous stages. Existing databases must already be present under `/data`; no source DB is uploaded or copied to GitHub. Run the below from deployed repository directory after Stage3B312 script is available:

```bash
python scripts/apex_stage3b312_linkage_runtime_verification.py \
  --mode local-audit \
  --root /data \
  --stage3b311-report evidence/stage3b311-validation.json \
  --deployment-history /data/apex_audit_evidence/stage3b38-deployment-history.json \
  --native-evidence /data/apex_audit_evidence/stage3b38-render-native-evidence.json \
  --max-rows 10000 --batch-size 200 --query-budget-ms 500 \
  --total-budget-ms 30000 \
  --output /tmp/apex-stage3b312-linkage-runtime-verification.json
```

**Important:** historical decisions and gamma observations are queried read-only with Stage 3B.3.10's indexed keyset walk, bounded query deadlines and row-count reconciliation. The outputs contain aggregate counts only. If a dependency or database file is missing, the report fails closed. The output is deliberately outside `/data`. The report has no runtime-activation attestation even if the linkage and deployment lifecycle correlate. No API keys are required; no Render API queries are made. For a mutable live database, use an independently consistent point-in-time backup **only if already available** and separately document its acquisition integrity; the script does not create/copy a backup.

### Alternative: review an existing Stage3B310 JSON report offline
This skips any DB access and reuses an existing aggregate report. Transfer only aggregated JSON files, not raw database records:
```bash
python scripts/apex_stage3b312_linkage_runtime_verification.py \
  --mode review \
  --stage3b310-report /path/to/stage3b310-origin-population.json \
  --stage3b311-report evidence/stage3b311-validation.json \
  --output /tmp/apex-stage3b312-review.json
```

## Interpretation
- `LINKAGE_POPULATION_RECONCILED_RUNTIME_NOT_ATTESTED`: stored decision↔gamma ID/symbol/time correlations reconciled for the currently visible bounded population; *not* proof of the gamma behavior active in the writing process.
- `SEMANTIC_FIXTURES_PASSED_LINKAGE_NOT_RECONCILED`: previous semantic tests passed; actual population not established.
- `INSUFFICIENT_EVIDENCE`: one or more required sources absent or invalid.
- Even if report `deployment_lifecycle_correlated=true`, `runtime_activation_attested=false`. Lifecycle events and record-embedded release strings cannot prove which code executed. To clear remaining gates requires genuinely independent, timestamped runtime traces tied to exact decision IDs plus trusted provenance and provider acquisition evidence; those have not been supplied.
- No previous policy date is asserted as effective. The September 18 deployment completion is only a reference timestamp.
- `utf8_reader_fix`, full replay, archive cutover, restore and rollback remain outside scope.

## Expected review
Review `status`, `sources`, `population_gate`, `runtime_gate`, `gate_results`, `remaining_gates`; upload only `/tmp/apex-stage3b312-linkage-runtime-verification.json` for review.
