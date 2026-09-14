# APEX 69.10.9 Build Report

**Build:** Trigger Observatory Retention & Evidence Payload Governance

## Repository audit findings
- Current reconstructed canonical baseline: 69.10.8.
- Trigger Observatory schema stores `evidence_json` directly on every observed trigger; canonical-decision capture previously passed the full decision object into that field.
- 69.10.8 already bounded future evidence-pipeline decision snapshots via the 69.4.4 projection, but had no second hard ceiling for unrelated top-level runtime bulk.
- Existing storage governance intentionally prohibited automatic raw-trigger pruning.

## Implementation
- `engine.trigger_observatory`: bounded future trigger evidence payloads; default ceiling 32 KiB; source byte count/hash retained when projection occurs.
- `engine.evidence_pipeline`: second forward-only hard size guardrail, default 128 KiB; historical rows untouched.
- `engine.storage_retention`: read-only Trigger Observatory retention diagnostics and explicit operator prune function.
- `scripts/apex_storage_maintenance.py`: `prune-trigger-observations`, dry-run default, explicit `--apply` required.
- Release manifest and Capability Registry synchronized to 69.10.9.

## Validation
- 65 APEX 69.10.x + consolidation tests passed.
- 45 focused closure/regression tests passed.
- 727 Python files compiled, 0 errors.
- Architecture Integrity: HEALTHY; release/registry 69.10.9; identity aligned; 59 capabilities.
- Flask-dependent trigger-route test collection is unavailable in this sandbox because Flask is not installed; no full Flask-suite claim is made.

## Production verification required
After deployment inspect `/api/admin/storage/audit` for `trigger_observatory_retention`. Do not apply pruning until the production eligibility/protection counts are reviewed. The build does not claim filesystem bytes reclaimed merely from SQLite DELETE.
