# APEX 13.0 Sprint 4 — Deployment and Rollback

## GitHub / Render deployment
1. Back up persistent SQLite volumes before deployment.
2. Commit the complete repository contents to the production GitHub branch.
3. Confirm Render uses persistent storage for `APEX_SIMILARITY_DB` when long-term vector retention is required.
4. Optional environment variable: `APEX_SIMILARITY_DB=/var/data/apex_similarity.db` or the appropriate Render disk path.
5. Deploy normally. Database initialization is idempotent and runs on first service use.
6. Verify `/api/research/institutional-status`, `/api/research/schema`, and `/apex_os/institutional_similarity`.
7. Build vectors from existing evidence using `POST /api/research/vectors/build` with an appropriate limit.

## Rollback
1. Redeploy the prior Sprint 3 commit or ZIP.
2. The additive `apex_similarity.db` can remain in place; prior releases do not depend on it.
3. To fully remove Sprint 4 data, archive and then remove only the similarity database identified by `APEX_SIMILARITY_DB`.
4. Do not delete the Recommendation Ledger, evidence, data-quality, or governance databases.

## Database notes
- New database/table changes are additive and backward compatible.
- Schema initialization uses `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE`.
- Stored vectors are immutable; correcting source evidence requires a future explicit schema/version migration rather than in-place mutation.
