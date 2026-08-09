# APEX 66.3.2 Deployment & Rollback

## GitHub deployment
1. Upload the contents of `APEX_66_3_2_CHANGED_FILES.zip` to the existing repository while preserving paths.
2. Commit message:
   `APEX 66.3.2 — Stateful Thesis Persistence & Structured Invalidation Lifecycle`
3. Push/commit to the branch used by Render (normally `main`).

## Render settings
Build command:
`pip install -r requirements.txt`

Start command:
`./start_render.sh`

A normal deploy is sufficient. No cache clear is required.

## Post-deployment validation
Verify:
- `/api/system/version` reports `66.3.2`.
- `/api/institutional-decision` reports `engine_version: 66.3.2` and thesis schema `apex.institutional_thesis.v2`.
- `/api/institutional-thesis` returns lifecycle metadata.
- `/api/institutional-thesis/history?ticker=SPX&session_date=<session>` returns persisted state after a live thesis has been created.
- Closed weekend access with no prior thesis does not create a new persisted weekend record.
- During RTH, an ACTIVE thesis receives a stable `thesis_id` and increasing revision only when the thesis materially changes.
- Explicit hard invalidation transitions to `INVALIDATED`, returns `NO_TRADE`, and status `THESIS_INVALIDATED`.

## Database behavior
Two tables are created additively in the existing recommendation-ledger database when thesis persistence first runs:
- `institutional_thesis_state`
- `institutional_thesis_events`

No existing tables are dropped or rewritten. No historical learning records are backfilled or fabricated.

## Rollback
1. Revert the GitHub commit for APEX 66.3.2.
2. Redeploy the prior **66.3.1** commit/build using the same Render settings.
3. Do **not** delete or downgrade production databases.
4. The two additive 66.3.2 thesis tables may remain; 66.3.1 does not use them.

Rollback does not require a database down-migration.
