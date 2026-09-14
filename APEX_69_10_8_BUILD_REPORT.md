# APEX 69.10.8 Build Report

## Release

- Version: `69.10.8`
- Build: `Storage Retention & Capacity Governance Closure`
- Production effect: `OPERATIONS_ONLY`
- Decision authority: none
- Execution authority: none

## Repository audit finding

The repository contained two incompatible storage-capacity defaults:

- `engine.storage_retention`: WARNING below 25%, CRITICAL below 15%
- `engine.operational_runtime`: WARNING at/below 15%, CRITICAL at/below 7%

This explains the production snapshot at 12.93% free reporting top-level `WARNING` even though the governed storage-retention policy considered that capacity critical.

The audit also confirmed that existing maintenance functions were intentionally manual and bounded: price samples can be pruned only behind pending-decision evidence, corrupt quarantine artifacts require operator apply, WALs can be checkpointed, and active-database VACUUM is prohibited.

## Implementation

1. Added `engine/storage_capacity_policy.py` as the canonical shared threshold policy.
2. Aligned `engine.operational_runtime.storage_status()` with the canonical 25% / 15% defaults.
3. Expanded `engine.storage_retention.audit()` with per-database SQLite allocation diagnostics, largest-database ranking, read-only price-prune planning, and explicit capacity actions.
4. Added `scripts/apex_storage_maintenance.py`; dry-run is default and all mutation requires `--apply`.
5. Registered canonical storage threshold environment variables in configuration governance while preserving legacy threshold names.
6. Upgraded `/api/admin/storage/audit` to schema `apex.storage_audit.v2` without making it mutable.
7. Synchronized release manifest and Capability Registry to 69.10.8.
8. Added 69.10.8 regression tests and ratcheted current-release identity tests.

## Safety properties

- no automatic delete
- no automatic VACUUM
- no active database unlink
- no canonical evidence deletion
- no raw trigger-observation automatic prune
- no trade-decision changes
- no execution-authority changes
- SQLite freelist reuse is not represented as filesystem reclaim
- CRITICAL capacity recommends disk expansion before unsafe compaction

## Validation

- APEX 69.10.x + consolidation + operational-hardening regression set: 65 passed
- Storage/configuration focused regression: 25 passed, 1 Flask-dependent test deselected
- Initial storage/69.10 closure focused set: 35 passed
- Python compilation: 726 files, 0 errors
- Architecture Integrity: HEALTHY
- release identity aligned: 69.10.8 / 69.10.8
- capability count: 59

Flask is not installed in the sandbox. Flask-dependent route-render/runtime tests were not claimed as passing.

## Post-deployment verification

At the production free-space level previously observed near 12.93%, both top-level storage status and `/api/admin/storage/audit` should now report `CRITICAL` under default configuration.

Use the v2 storage audit to identify the largest SQLite tables and exact operator-cleanup eligibility before applying maintenance. Do not infer that deleting SQLite rows will immediately increase filesystem free bytes.
