# GitHub, Render, and Rollback Notes

## GitHub

1. Upload or merge the complete repository contents into the current production branch.
2. Review `APEX_11_X_12_X_FILE_MANIFEST.md`.
3. Run `python -m pytest -q` in CI.
4. Do not commit runtime SQLite files created after deployment unless that is already the repository's established persistence policy.

## Render

- Keep the existing start command and environment variables.
- Add a persistent disk for the governance database when durable history is required.
- Optional environment variables:
  - `APEX_GOVERNANCE_DB=/var/data/apex_governance.db`
  - `APEX_MIN_GRADED_HISTORY=50`
  - `APEX_MIN_SIMILAR_OUTCOMES=20`
- Redeploy and verify:
  - `/api/history/status`
  - `/api/research/status`
  - `/api/learning/status`
  - `/apex_os/institutional_research`
  - `/apex_os/adaptive_learning`

## Rollback

1. Revert to the prior Git commit or redeploy the previous Render build.
2. Retain a copy of `apex_governance.db`; it is additive and does not alter the old ledger.
3. Confirm legacy Operations, Execution OS, Recommendation Ledger, Mission Control, and Trade Command routes.
4. Candidate rollback is also available through `POST /api/learning/candidates/<id>/rollback`; it records an audit event and disables the candidate.
