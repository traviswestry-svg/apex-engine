# APEX Stage 3B.3.13 — Historical Producer-Origin & Runtime Activation Evidence Audit

**Candidate only.** Standalone bounded, read-only evidence-correlation utility, NOT a production-data validation or migration authorization. `BLOCKED_RESEARCH_ONLY` always.

## Contents

- `scripts/apex_stage3b313_producer_runtime_evidence_audit.py`: accepts the existing *aggregate* Stage 3B.3.12 report and **optional pre-existing local** event files; joins exact identifiers and event timestamps **in process memory only**; writes aggregate evidence-status JSON outside `/data`. No raw IDs, event timestamps or payloads in output.
- `tests/test_apex_stage3b313_producer_runtime_evidence_audit.py`: 17 offline synthetic regression tests.
- `.github/workflows/apex-stage3b313-producer-runtime-audit.yml`: manually triggered or PR-scoped **synthetic tests only**. GitHub does not access production records. Your existing CI is unchanged.

## GitHub Desktop deployment

1. Extract the ZIP into the root of the APEX checkout, retaining all paths.
2. Create branch `apex-stage3b313-producer-origin-runtime-audit`.
3. Commit, push, create PR to protected `main`; review existing APEX CI and new Stage 3B.3.13 test results before merging. No production migration, feature flags or trade execution changes.

## Render Shell: run a read-only evidence inventory without trace inputs

The prior Stage 3B.3.12 aggregate report was generated in Render Shell at `/tmp/apex-stage3b312-linkage-runtime-verification.json`. **Temporary files may disappear on instance restart/deployment.** If absent, regenerate Stage 3B.3.12 using the previously successful read-only command; do not invent the report.

```bash
python -m unittest discover -s tests -p 'test_apex_stage3b313_producer_runtime_evidence_audit.py' -v

python scripts/apex_stage3b313_producer_runtime_evidence_audit.py \
  --stage3b312-report /tmp/apex-stage3b312-linkage-runtime-verification.json \
  --output /tmp/apex-stage3b313-producer-runtime-evidence.json

python -m json.tool /tmp/apex-stage3b313-producer-runtime-evidence.json
```

Expected status when no existing traces are provided: `TRACE_INPUTS_INCOMPLETE_RUNTIME_UNVERIFIED`. This is an **honest outcome**, not a tool failure. Historical reconciliation remains inherited from Stage 3B.3.12, not repeated. No SQLite connections, Render API calls, Github credentials, historical code execution, or exports are required.

## If genuine historical first-party trace files already exist

Use only **pre-existing** local files with independently known provenance; do **not** regenerate or retroactively backfill purported historical traces. The script will not discover, transform, or create these events. It will correlate claims only; such correlation is not independent attestation.

Each input is a bounded UTF-8 JSON Lines (`.jsonl`) file with one object per line, schema field `"schema":"apex.stage3b313_trace.v1"`, and these required fields:

| Input | `kind` | Required fields in addition to `schema` and `kind` |
|---|---|---|
| `--decision-events` | `decision` | `decision_id`, `snapshot_id`, `boot_id`, `producer_commit` (40/64 hex), `decision_at` |
| `--boot-events` | `boot` | `boot_id`, `commit_sha` (40/64 hex), `boot_at` |
| `--gamma-execution-events` | `gamma_execution` | `decision_id`, `snapshot_id`, `boot_id`, `executed_at`, `feature_enabled` (Boolean) |
| `--provider-capture-events` | `provider_capture` | `snapshot_id`, `received_at`, `persisted_at` |

All timestamps must be timezone-aware ISO-8601. The four source types are required for three-way correlation. A **true** `feature_enabled` field is only a first-party claim; it is never promoted into independent execution proof. Runtime event time must be between matching boot time and decision time; provider receipt must precede persistence and decision. Exact decision, gamma ID, boot ID, and commit equality are enforced. Duplicate IDs fail closed.

```bash
python scripts/apex_stage3b313_producer_runtime_evidence_audit.py \
  --stage3b312-report /tmp/apex-stage3b312-linkage-runtime-verification.json \
  --decision-events /path/to/preexisting-decision-events.jsonl \
  --boot-events /path/to/preexisting-boot-events.jsonl \
  --gamma-execution-events /path/to/preexisting-gamma-execution-events.jsonl \
  --provider-capture-events /path/to/preexisting-provider-capture-events.jsonl \
  --max-events-per-file 10000 \
  --output /tmp/apex-stage3b313-producer-runtime-evidence.json
```

Do not run if those trace files don't genuinely exist. Inputs are never copied/uploaded to GitHub or exported. The audit limits each file to 16 MiB, each line to 16 KiB, and 10,000 records by default, rejects symlink inputs and non-regular files, and fails closed on malformed evidence. `input_sha256` values identify the exact input bytes but **do not prove historical authenticity**. Do not upload raw traces or production databases; share **only the aggregate output**.

## What this stage **cannot** establish

1. Decision records and gamma observations are not joined to the Stage 3B.3.12 **entire population** by ID (prior report exports no IDs); any preexisting traces are a separately disclosed sample. Counts are *not* extrapolated to all 5,767 decisions.
2. First-party producer/boot, gamma-execution, and provider-capture records can establish **claimed correlations**, not independent execution attestation. A contemporaneous capture timestamp isn't proof the provider was actually available at decision time.
3. Report/file hashes cannot authenticate independent custody, writer origin, immutable log retention, or signature verification. The audit makes **no** independent activation or provider availability attestation.
4. Stage 3B.3.11 selected semantic fixtures remain the only completed isolated historical semantic checks. Full real historical decision replay, cross-database consistent snapshot, policy effective date and production cutover are outside scope.

**Acceptance criteria:** 17/17 tests; genuine Stage3B312 report accepted; no raw exports; absence/malformed evidence accurately reported; every attestation gate remains `UNVERIFIED` unless a *new independent attestation mechanism* is explicitly designed and reviewed; migration always `BLOCKED_RESEARCH_ONLY`.
