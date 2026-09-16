# APEX 69.10.13 Build Report

## Historical Payload Archive Pagination & Complete Shadow Validation Closure

Authoritative baseline: APEX 69.10.12 repository supplied 2026-09-16.

### Source-verified defect

`engine/historical_payload_archive.py` clamped archive and shadow actions to 500 rows and always selected the first deterministic source prefix. Repeated archive invocations therefore re-verified the same 500 archived rows and could not reach later historical rows. Shadow validation had the same first-prefix limitation.

### Closure

- Preserves the 500-row maximum per operator invocation.
- Archive batches now select the next deterministic unarchived source identities and load payload blobs only for that bounded set.
- Repeated archive invocations progress until `remaining_rows == 0` and report `archive_complete`.
- Archive results expose source rows, archived rows before/after, remaining rows, and the effective batch limit.
- Shadow validation now accepts a read-only `--offset` and reports `next_offset`, source rows, and `validation_complete` for deterministic page-by-page full-source coverage.
- Existing immutable archive, SHA-256, exact round-trip, critical-capacity, explicit-apply, and no-source-mutation guardrails remain intact.
- No production reads are redirected. No canonical rows are rewritten or deleted. No VACUUM, decision authority, execution authority, broker mutation, or trading/risk behavior change is introduced.

### Validation

- 91 relevant APEX 69.10.x, consolidation, and operational-hardening tests passed.
- 733 Python files compiled with 0 errors.
- Architecture Integrity: HEALTHY; release/registry aligned at 69.10.13; capability count 63; no missing modules, duplicate routes, or cleanup violations.
- Flask-dependent `tests/test_operational_health.py` could not be collected in the local build environment because Flask is not installed. No runtime production outcome is claimed from local validation.

### Production verification required

After deployment, continue using bounded 500-row archive invocations. Each successful invocation should advance `archived_rows_after` and reduce `remaining_rows`. Shadow validation should be run page-by-page with offsets 0, 500, 1000, etc. until the final page reports `validation_complete: true`, with zero archive misses, mismatches, and projection errors on every page.
