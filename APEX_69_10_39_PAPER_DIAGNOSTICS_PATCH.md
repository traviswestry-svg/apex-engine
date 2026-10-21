# APEX 69.10.39 — Paper diagnostics patch

**Scope:** Add an authenticated, read-only readiness endpoint and a strictly non-order-generating TradersPost connectivity probe. The canonical release version stays 69.10.39; no new environment variables are introduced.

## Endpoints

- `GET /api/paper/traderspost/readiness` — requires `X-APEX-Paper-Token` plus the existing dashboard/global authentication middleware. Redacts credentials. Reports flags and blockers; **never** claims unattended execution readiness.
- `POST /api/paper/traderspost/connectivity-test` — requires the same operator token and existing global authentication. Uses a *fixed* `ticker=SPX`, `action=buy`, `test=true` TradersPost payload. It accepts no caller-controlled trade fields, does not call APEX dispatch, does not create any paper order, and cannot establish a fill. Requires paper mode, explicit paper-account attestation, configured authorized webhook, enabled sends, and disabled E*TRADE live order routing. HTTP transport success is not a broker fill.

TradersPost's official webhook reference documents `test: true` as processing without sending orders to the broker: https://docs.traderspost.io/docs/developer-resources/webhook-reference . Verify this behavior in TradersPost before relying on it; availability/outages remain possible.

## Known blockers (deliberate)

- Existing dispatch trusts caller-supplied governance and human approval flags rather than verifying immutable canonical decisions.
- No bidirectional position/fill reconciliation with TradersPost built-in paper account.
- No proven realized daily loss lockout across execution routes.
- Existing separate quote-grading model does not establish realized or broker-confirmed P&L.
- Scanner memory and learning problems from prior production health report remain out of scope.

Do not enable unattended execution based on these diagnostics. Keep TradersPost in manual submission for controlled tests.

## Local checks

- Diagnostic/paper focused: 9 passed; 2 skipped (Flask unavailable).
- Configuration, release-truth and gamma-transition selected tests: 21 passed, 1 failed because Flask unavailable.
- Full pytest collection: 68 collection errors (missing Flask); not CI certified.
- Python `compileall` on changed code/tests: passed.

## Authentication and usage

Browser requests from an authenticated APEX website session must additionally provide `X-APEX-Paper-Token`. Never place token or TradersPost webhook URL in screenshots, logs, query parameters or source. On a valid session, test `GET /api/paper/traderspost/readiness` first, and only intentionally invoke the non-order test POST when ready. **Do not POST /api/paper/traderspost/dispatch as a connectivity test.**

## Rollback

Revert `engine/execution/trade_routes.py` and `engine/execution/traderspost_paper.py` to their previous commit; remove `tests/test_apex_69_10_39_paper_diagnostics.py`. Both new endpoints then disappear; existing paper gateway remains unchanged.
