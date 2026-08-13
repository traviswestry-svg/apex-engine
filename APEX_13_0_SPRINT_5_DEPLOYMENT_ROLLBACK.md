# APEX 13.0 Sprint 5 — GitHub, Render, and Rollback

## GitHub deployment
1. Back up the current production branch and persistent SQLite files.
2. Extract the complete repository ZIP into the repository root or apply the changed-files ZIP.
3. Commit the Sprint 5 files.
4. Push to the Render-connected branch.

## Render
- No new Python package is required.
- Optional persistent-disk variable: `APEX_RESEARCH_DB=/var/data/apex_research.db`.
- Optional thresholds:
  - `APEX_RESEARCH_MIN_COHORT=20`
  - `APEX_RESEARCH_MIN_COMPARISON_COHORTS=2`
  - `APEX_RESEARCH_MATERIAL_GAP_PCT=10`
- Keep `APEX_GOVERNANCE_DB` and `APEX_DATA_QUALITY_DB` on persistent storage.
- The migration is additive and idempotent. The database is created on first route/service use.

## Post-deployment checks
- `GET /api/research/status`
- `GET /api/research/comparisons?dimension=family`
- `GET /api/research/findings`
- `GET /apex_os/strategy_intelligence`

Expected before sufficient history: `COLLECTING` or `INSUFFICIENT_HISTORY`, with no findings and no production policy effect.

## Rollback
1. Redeploy the Sprint 4 commit or restore the Sprint 4 repository ZIP.
2. The additive `apex_research.db` may remain in place; Sprint 4 does not read it.
3. To fully remove Sprint 5 research state, archive and then remove only `apex_research.db` after rollback.
4. Do not alter Recommendation Ledger, evidence, quality, governance, or similarity databases.
