# APEX 48.2.1 — Session-Aware Morning Readiness

## Purpose
Morning Readiness now reflects the true operational state of APEX instead of
reporting false `FAIL`s whenever the market is closed. Items that are simply
unavailable outside a live session (quotes, liquidity, live recommendation) read
as `CLOSED` / `NOT_EXPECTED` / `WAITING` — not `FAIL`. `FAIL` is reserved for a
condition that should hold during a live session but does not.

This is a UX, state-modeling, and operational-readiness change. It does **not**
touch trading logic, scanner logic, recommendations, adaptive learning,
execution scoring, or risk calculations.

## What changed
- **New:** `engine/session_readiness.py` — a pure presentation layer defining the
  rich `ReadinessState` model (`READY`, `OPEN`, `WAITING`, `NOT_EXPECTED`,
  `NOT_REQUIRED`, `CLOSED`, `DISCONNECTED`, `FAIL`), the intelligent
  `OverallStatus` roll-up (`READY`, `STANDBY`, `WAITING`, `ACTION_REQUIRED`,
  `FAILURE`), the color map, and per-row help text. It only *interprets* state
  other services already computed; it contains no session-*detection* logic.
- **Extended:** `engine/institutional_execution_os.py` — `build_morning_readiness`
  now attaches a session-aware `checklist`, `overall_status`,
  `overall_headline`, `overall_detail`, `overall_color`, and normalized
  `session`. All legacy fields (`score`, `status`, `trading_mode`,
  `components`, `blocking_items`, `recommendation`) are preserved unchanged.
- **Extended:** `engine/execution_os_routes.py` — `register_execution_os_routes`
  accepts optional `session_provider` and `risk_config_provider`. The readiness
  route now decides open/closed from the **canonical session detector**, so it is
  correct even when no scanner result exists (e.g. weekends).
- **Wired:** `app.py` and `engine/app.py` — pass `system_mode()` as the session
  provider (no duplicate session logic) and the loaded global risk limits as the
  risk-config provider.
- **UI:** `templates/execution_os.html` — the Institutional Checklist renders
  rich state chips with the spec color mapping and per-row tooltips, plus an
  intelligent overall-status banner. Shown on both the Execution and Morning
  Readiness tabs.

## Architecture
Reuses the existing session detector (`session_status` / `system_mode`), the
existing execution-snapshot checks (`build_execution_snapshot`), and the existing
health service (`_all_checks`). No business logic is duplicated. Morning
Readiness is now a presentation layer over those objects.

## Closed-market result (verified)
```
Broker         -> NOT_REQUIRED   (gray)
Market         -> CLOSED         (gray)
Chain Gate     -> READY          (green)
Quotes Present -> NOT_EXPECTED   (gray)
Quotes Fresh   -> NOT_EXPECTED   (gray)
Liquidity      -> NOT_EXPECTED   (gray)
Recommendation -> WAITING        (blue)
Risk           -> READY          (green)
Overall: STANDBY — Market Closed — Awaiting next trading session
FAIL rows: NONE
```
Note: the **Broker** row reads `NOT_REQUIRED` (not `READY`) while no E*TRADE
session is authenticated. It becomes `READY` once the broker is connected and
`DISCONNECTED` (→ `ACTION_REQUIRED`) only when a live recommendation needs it.
This is the honest reading of the state model and still satisfies "never FAIL
outside trading hours."

## Guardrails honored
No changes to scanner, recommendations, execution scoring, learning, evidence
pipeline, databases, or the release manager.

## Tests
`tests/test_session_readiness.py` (16 tests) covers weekend, holiday, premarket,
open market, live recommendation, recommendation waiting, broker disconnected,
quotes stale/healthy, risk configured/missing, backward compatibility, and the
expected closed-market UI. The 4 pre-existing `tests/test_execution_os.py` tests
still pass unchanged.
