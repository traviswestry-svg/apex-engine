# APEX 64.1 Frontend and Backend Hotfix

## Corrected defects

1. Registered the previously orphaned recommendation-ledger Flask route module. This restores:
   - `/api/recommendation-ledger/health`
   - `/api/recommendation-ledger/coverage`
   - `/api/calibration/readiness`
   - the remaining recommendation-ledger lifecycle endpoints

2. Corrected the Similarity Lab status panel. The page used `status` as an implicit browser global, which collided with `window.status`; the API could return successfully while the panel stayed on `Loading...`. All elements now use explicit `document.getElementById` references and non-2xx responses are surfaced.

3. Corrected the Historical Readiness status badge. It had the same `window.status` collision, causing the badge to remain `LOADING` even though the report cards populated. The page now uses explicit DOM references, null-safe response rendering, HTTP validation, and visible error states.

4. Preserved the APEX 64 Trade Assistant Director and Trade Director market-memory fixes from the preceding hotfix.

## Files changed

- `app.py`
- `engine/trade_director_market_memory.py`
- `templates/assistant.html`
- `templates/institutional_similarity_lab.html`
- `templates/historical_readiness_dashboard.html`

## Validation

- Python compilation passed.
- Similarity Lab JavaScript syntax passed `node --check`.
- Historical Readiness JavaScript syntax passed `node --check`.
