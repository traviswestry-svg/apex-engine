# APEX Trade Director Phase 33 — Trader Workflow Interface

## Purpose
Phase 33 redesigns the live trading presentation without replacing engines, routes, schemas, or execution controls.

## Implemented
- Added a decision-first Trader Cockpit to `/apex_os`.
- Prioritized bias, entry, invalidation, target, readiness/size, strategy, risk gate, and broker state.
- Moved supporting architecture cards behind an expandable context section.
- Removed phase-number labels from the live `/assistant` presentation while preserving every underlying module.
- Added responsive workflow styling and DOM-safe synchronization with existing dashboard values.
- Preserved confirmation gating, locked broker state, APIs, and existing dashboard IDs.

## Files
- `templates/apex_os.html`
- `templates/assistant.html`
- `static/css/trader_workflow.css`
- `static/js/trader_workflow.js`
- `tests/test_trade_director_phase33.py`
- `APEX_TRADE_DIRECTOR_PHASE_33_BUILD.md`

## Upgrade Notes
No database migration is required. Deploy as a normal application update. Browser cache busting continues to use the existing asset version query.

## Validation
- Python compilation: PASS
- Phase 33 focused tests: 4 passed, 0 failed
- Trade Director Phase 13–33 regression suite: 88 passed, 0 failed
- `static/js/apex_os.js` syntax: PASS
- `static/js/trader_workflow.js` syntax: PASS
- Full repository collection: BLOCKED by missing Flask dependency in 42 test modules
- ZIP integrity: verified after packaging
