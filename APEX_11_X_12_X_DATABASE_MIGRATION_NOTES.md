# Database and Migration Notes

## New governed database

Default file: `apex_governance.db` (override with `APEX_GOVERNANCE_DB`). It is created on first start and is not included with synthetic rows.

Schema version: **4**, tracked in `governance_schema`.

Tables:

- `historical_events`: append-only normalized evidence events with provenance and SHA-256 integrity hashes.
- `graded_outcomes`: one immutable outcome per recommendation.
- `feature_vectors`: versioned, hashed feature vectors with observed timestamps.
- `model_registry`: versioned offline candidates and approval state.
- `shadow_results`: production-versus-candidate observations.
- `drift_events`: drift evidence and review state.
- `governance_audit`: append-only governance actions.

Indexes cover recommendation/time, event type/time, outcome family/time, vector time/hash, model status, shadow candidate/time, drift time, and audit time.

## Compatibility

No existing production table is dropped, rewritten, or migrated destructively. Existing recommendation ledger rows remain readable. Initialization uses `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE`, so startup is idempotent.

## Rollback

1. Deploy the previous repository release.
2. Preserve `apex_governance.db` as an audit artifact; the previous release does not depend on it.
3. Do not delete or rewrite the existing recommendation ledger database.
4. To disable the new storage without data loss, point `APEX_GOVERNANCE_DB` to a quarantined path or remove new route registration while retaining the database backup.
