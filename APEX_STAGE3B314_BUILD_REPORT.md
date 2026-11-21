# APEX Stage 3B.3.14 — Existing Historical Evidence Source Metadata Inventory

**Candidate only; read-only metadata discovery. No independent runtime attestation. Migration authority: `BLOCKED_RESEARCH_ONLY`.**

## Reason for this build

Stage 3B.3.13 completed its inventory of supplied evidence but received **no decision, producer-boot, gamma-execution, or provider-capture trace files**. Stage 3B.3.12's previously reconciled 5,767 decisions are not re-read in this stage. Stage 3B.3.14 discovers *possible* existing evidence locations before constructing more correlation machinery.

## Contents

- `scripts/apex_stage3b314_evidence_source_inventory.py`: read-only, bounded SQLite **schema metadata** and filesystem **file metadata** scanner. Never reads decision rows or log content. Candidate paths are represented by opaque SHA-256-derived references, not full paths. Exposes table/column schema names that match specific producer/runtime/provider/decision keywords. File names are used for classification but not exposed.
- `tests/test_apex_stage3b314_evidence_source_inventory.py`: 17 synthetic tests, including no-row-export and no-writes assertions.
- `.github/workflows/apex-stage3b314-evidence-inventory-tests.yml`: synthetic tests in GitHub only; no production mounts, secrets or Render API calls.

## Install with GitHub Desktop

1. Extract this ZIP over a **new branch** of your local `apex-engine` checkout, preserving the internal directories.
2. Branch name: `apex-stage3b314-evidence-source-inventory`.
3. Push and open a pull request into protected `main`.
4. Review changes and pass required APEX CI before merging and deploying through the existing controlled process. No changes to app startup, jobs, live trading, SQLite schema, or ingestion.

## Run on Render (metadata-only)

From `~/project/src` on the running Render service:

```bash
python -m unittest discover -s tests -p 'test_apex_stage3b314_evidence_source_inventory.py' -v

python scripts/apex_stage3b314_evidence_source_inventory.py \
  --root /data \
  --stage3b313-report /tmp/apex-stage3b313-producer-runtime-evidence.json \
  --max-files 250 \
  --max-depth 3 \
  --max-tables 400 \
  --budget-seconds 20 \
  --output /tmp/apex-stage3b314-evidence-source-inventory.json

python -m json.tool /tmp/apex-stage3b314-evidence-source-inventory.json
```

If the Stage 3B.3.13 report disappeared during deployment, **omit `--stage3b313-report`**; the scan still works and explicitly records `NOT_SUPPLIED`. Do not fabricate or recreate old production traces. The output filename must not exist already: use a new name for each run, or explicitly remove an older generated `/tmp` report if desired. No input files or database records are altered.

## Reading the results

- `BOUNDED_INVENTORY_COMPLETED`: completed the configured depth/count/time-bounded metadata inventory, **not** proof all potential sources exist in `/data`.
- `PARTIAL_INVENTORY`: limits, unreadable directories or time budget prevent complete bounded inventory; increase bounds only after reviewing resource impact.
- Each `SQLITE_SCHEMA` item reports `METADATA_INSPECTED`, `TABLE_LIMIT_EXCEEDED`, or `UNREADABLE_OR_INVALID_SQLITE`. For inspected tables, metadata-only category matches include `producer_origin`, `runtime_execution`, `provider_capture`, and `decision_linkage`.
- Each `POTENTIAL_TRACE_FILE_METADATA` item was classified **from the filename only**; its content has not been opened or trusted.
- Opaque `file_ref` is a SHA-256 prefix of the path relative to the specified root. It provides stable correlation within the same root without publishing filenames, but isn't an authentication signature.
- All attestation fields remain `UNVERIFIED`. No event correlation, provider availability proof, origin attestation, snapshot consistency, or replay is done.

## Scope and limitations

1. Scans SQLite files with `.db`, `.sqlite`, `.sqlite3`, `.db3`, and potential trace files `.jsonl`, `.ndjson`, `.log`, `.json` beneath the chosen root. No Render API, external logs or GitHub workflow archives are queried.
2. SQLite connections use `mode=ro`, `PRAGMA query_only=ON` and `PRAGMA trusted_schema=OFF`; only `sqlite_master` table names and `pragma_table_info` column metadata are requested, not table rows. SQLite opening can interact with filesystem lock/journal state as normal for read-only connections; use a nonproduction copy if zero interaction with live file state is required.
3. The scanner does not descend through symlink entries. Candidates can exist outside `/data` and the chosen bounds; absence here is not proof of global absence.
4. Schema metadata can reflect *present-day* structure, even when records were created later than the September 2026 historical target. Never infer historical feature activation from schema presence.
5. Its output contains table/column schema names. Review before sharing if schema names are internal; **do not upload raw database/log files**.
6. No migrations, event-trace backfills, timestamp reassignment, producer-origin retrofitting, latest gamma substitutions, or trades.

## Acceptance and next decision

- 17 development tests pass.
- Inventory completes within configured bounds; possible candidates have explicit metadata-only confidence.
- Only if a genuinely contemporaneous existing source is found should Stage 3B.3.13 be re-run with **authentic**, separately reviewed trace inputs. Do not synthesize historical traces from current data.
- If no meaningful candidates are found, document the limits of retrospective attestation and retain `BLOCKED_RESEARCH_ONLY`.
