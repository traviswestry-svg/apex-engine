# APEX 69.10.37 — Production Promotion & Diagnostic Persistence Closure

Base: uploaded 2026-10-09 repository, previously labeled 69.10.36.

- Promotes canonical release manifest and registry to 69.10.37.
- Retains existing pre-outcome diagnostic capture in `engine/morning_brief.py`.
- Adds **read-only** `diagnostic_persistence` to existing `/api/morning-brief/archive-status?date=YYYY-MM-DD` response.
- Reads the original official immutable morning snapshot, never a revision, latest live brief, or Evening Recap.
- Legacy official forecasts remain `LEGACY_MISSING_NO_BACKFILL`; no reconstructed diagnostics.
- Includes prior CI compatibility test corrections; no trading, forecast, grade, or settlement behavior changes.

## Deployment gates
1. Run GitHub Actions smoke and ratcheted tests; ensure no version-assertion failures.
2. Verify Render's deployed Git SHA matches the intended GitHub commit; health reports 69.10.37.
3. After the next *new* pre-open official Morning Brief, check `/api/morning-brief/archive-status?date=YYYY-MM-DD`: `diagnostic_persistence.state=PERSISTED_VERIFIED`.
4. Check `/api/morning-brief/archive/YYYY-MM-DD` contains `structured.forecast_provenance_diagnostics` and canonical provenance.
5. Check cached Evening Recap still validates the same forecast ID and snapshot hash.
6. Do not interpret an old archive's missing diagnostics as a deployment failure.

This package does **not** prove live Render deployment or production DB readback. It does not include incomplete 69.10.38 changes.
