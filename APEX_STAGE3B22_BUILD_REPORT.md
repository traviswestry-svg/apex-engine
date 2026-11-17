# APEX Stage 3B.2.2 — Build report

## Purpose
Read-only, metadata-only diagnosis of historical archived payloads that exceeded the 256 KiB comparison limit in Stage 3B.2.1. No decompression or archive BLOB / canonical JSON retrieval.

## Implementation
- Independent operator-run `scripts/apex_stage3b22_archive_metadata_provenance_audit.py`.
- Bounded oldest and newest archive rows per payload type (default 16 at each edge; 32 hard cap per edge); deduplicates overlapping edges.
- Grouped archived original-byte and compressed-byte size summaries with sampled bins; metadata-driven ratios must not be interpreted as validated storage savings.
- Aggregated archive creation month and version/schema/integrity-label metadata with strict token validation.
- Validates payload type / source table / source column metadata against known existing `PAYLOAD_TYPES` mapping.
- Indexed source primary-identity lookup and timestamp text agreement using a fixed, bounded query. Skips if the query plan is not indexed.
- Never selects `archive_blob`, `snapshot_json`, or `evidence_json`. Never exports row identifiers or raw timestamps, hashes, payloads, or filenames from database rows.
- Cooperative SQLite per-query and total budgets; no mutation, migration, replay, `VACUUM`, checkpoint or archive retention changes.

## Validation
16 focused isolated SQLite fixture tests passed. Full repository CI not executed; production deployment and production probe are pending.

## Run after source review, CI and deployment
```
python scripts/apex_stage3b22_archive_metadata_provenance_audit.py \
  --root /data \
  --sample-rows 16 \
  --query-budget-ms 400 \
  --total-budget-ms 8000 \
  --output /tmp/apex-stage3b22-metadata.json
cat /tmp/apex-stage3b22-metadata.json
```

## Interpretation limits
The sample is bounded and biased to both archive insertion-order edges; it is not a full longitudinal distribution. Source presence plus timestamps is **not** archive-to-source payload correspondence. Size fields are declared archive metadata, not validated actual bytes. Legacy `ZLIB_9` reader UTF-8 fault remains separately gated. Production migration stays `BLOCKED_RESEARCH_ONLY`.
