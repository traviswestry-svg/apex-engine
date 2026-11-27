# APEX Session Authority Hardening — Review Candidate

**Status:** BUILT / LOCAL TESTS PASSED / NOT DEPLOYED / EXECUTION NO_GO

## Grounding

Built against the user-provided `apex-engine-main(20261121-191801).zip` source archive and checked against the pasted November 27, 2026 live Render excerpts (`app.py`, `canonical_market_calendar.py`, `trade_routes.py`, `trade_risk_guard.py`, `apex_engines.py`, `live_operations.py`). This is a **changed-files-only overlay**, not an automatically merged production patch. Reconcile against current `main` before applying. No release manifest or version bump is included.

## Changed files

- `engine/canonical_market_calendar.py`: adds bounded 2026–27 calendar schedule and conservative SPX RTH close, explicitly including 2026-11-27 at 13:00 ET. Existing historical `classify` now respects early closes. Unsupported years deny RTH eligibility.
- `app.py`: `session_status()` reads canonical RTH eligibility rather than fixed 16:00; `/health`, market panel, and market session context already derive from this function.
- `engine/execution/trade_risk_guard.py`: independently validates current exchange time in single- and multi-leg entry validation, even when supplied a forged `MARKET_OPEN`; defaults to UNKNOWN. It retains no-new-entries cutoff and live trading gates.
- `engine/execution/trade_routes.py`: removes five client `session_state` inputs; derives entry state server-side; complex preview gains prevalidation before broker preview. Existing live-routing flag preserved.
- `apex_engines.py`: consensus market label uses canonical schedule.
- `engine/live_operations.py`: uses `America/New_York` rather than fixed UTC-4; consults canonical early-close dates.
- `tests/test_apex_session_authority_hardening.py`: eight broker-free deterministic regression checks.

## Local validation

```
PYTHONPATH=. python -m unittest tests.test_apex_session_authority_hardening -v
PYTHONPATH=. python -m pytest -q tests/test_apex_69_10_32_1_session_calendar_integrity_closure.py tests/test_spxo_contract_compatibility.py
```

Observed on the isolated source checkout: **8/8** new tests, **16/16** selected existing tests. All changed Python modules compile.

## Critical limitations and release blockers

1. The in-source `EARLY_CLOSE_ET` mapping is **NOT a complete authoritative exchange calendar** and may omit exceptional closures, changes, or SPX vs SPXW instrument-specific trading windows. Do not enable live routing based solely on this patch. Before production sign-off, integrate and test maintained **Cboe/product-specific** calendar authority with verified daily schedule and fail-closed behavior when unavailable, plus independent broker enforcement.
2. This patch changes the classification used for SPX **regular-session entries**, not ES futures or overnight schedules. Existing `AFTER_HOURS` label means SPX cash session closed, **not** that futures are necessarily open on a special schedule. Audit all futures-specific status labels separately.
3. Server-side guard protects `engine/execution` E*TRADE code paths reviewed here; **TradersPost paper gateway and any alternative submission paths remain unaudited**. Do not infer complete broker safety.
4. New validation rejects entries lacking explicit trusted `MARKET_OPEN`, even on ordinary weekdays. Test clients and callers that formerly relied on implicit default; update them as necessary.
5. Validate auth and idempotency, preview-vs-place boundary timing, code paths for protective exits/cancels, and whole test suite in staging. The live `APEX_LIVE_ORDER_ROUTING_ENABLED` environment flag was **not read or changed**.
6. Apply neither a live deployment nor `terraform apply` for this candidate automatically. No DB history, gamma records, system settings, or broker orders were touched.

## Pre-merge verification in current checkout

Run in a clean branch, after reviewing the changed files against current production source:

```
python -m compileall -q app.py apex_engines.py engine/canonical_market_calendar.py engine/live_operations.py engine/execution/trade_risk_guard.py engine/execution/trade_routes.py
PYTHONPATH=. python -m unittest tests.test_apex_session_authority_hardening -v
PYTHONPATH=. python -m pytest -q tests/test_apex_69_10_32_1_session_calendar_integrity_closure.py tests/test_spxo_contract_compatibility.py
```

Run complete production suite and paper-only sandbox probes, then promote only through normal change control. Verify 2026-11-27 12:59/13:00/15:28 ET and full-day holidays at `/health` and `/api/market_status`; ensure order-entry endpoints do not call adapters after close. Confirm protective exits remain permissible under their own policy. Keep live execution disabled.
