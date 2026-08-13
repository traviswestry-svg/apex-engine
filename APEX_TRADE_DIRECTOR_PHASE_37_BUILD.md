# APEX Trade Director Phase 37 Build

## Phase
**Phase 37 — Mobile Momentum Intelligence & Telegram Operations**

## Purpose
Phase 37 allows APEX to notify the trader's phone when the governed Momentum Burst environment progresses through meaningful states. The alert layer consumes Phase 35 trade-function routing and Phase 36 precision-entry lifecycle outputs. It is advisory only and never places, modifies, or closes a broker order.

## Alert State Machine
- `MOMENTUM_WATCH` — momentum evidence is developing.
- `MOMENTUM_PRIMED` — Momentum Burst is selected and entry quality/confidence clear governed thresholds.
- `ENTRY_WINDOW_OPEN` — the entry trigger is confirmed while risk, liquidity, and data health remain eligible.
- `SETUP_INVALIDATED` — the prior setup no longer satisfies its thesis.
- `TAKE_PROFIT` — Phase 36 reports that the premium expansion objective has been reached.
- `EXIT_NOW` — Phase 36 reports that the governed adverse-premium threshold has been breached.

## Backend Implementation
- Added `engine/trade_director_mobile_momentum_alerts.py`.
- Added append-only SQLite delivery history in `apex_mobile_alerts.db`.
- Added opportunity fingerprints, duplicate suppression, cooldown control, and state-regression suppression.
- Added transparent alert classification based on Momentum Burst selection, entry quality, institutional confidence, trigger state, data freshness, risk eligibility, and spread quality.
- Added Telegram message formatting with direction, function, entry quality, confidence, trigger, premium plan, dashboard link, and manual-execution warning.
- Failed deliveries are logged and remain visible rather than being represented as successful.

## API Integration
- `GET /api/mobile-momentum-alerts/status`
- `POST /api/mobile-momentum-alerts/evaluate`
- `POST /api/mobile-momentum-alerts/test`

The coordinated Institutional OS scan now evaluates Phase 37 non-fatally after the existing Trade Director composition. A Phase 37 failure cannot block the market-state response.

## Dashboard Integration
The `/assistant` page now includes a mobile operations panel showing:
- Telegram configuration status
- Last alert stage
- Delivery and failure counts
- Governed cooldown
- Recent alert history
- One-tap Telegram delivery test

The mobile panel uses a responsive layout suitable for phone operation.

## Configuration
Existing variables remain supported:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- Existing `SEND_TELEGRAM` gate

New optional variables:
- `APEX_MOMENTUM_ALERT_COOLDOWN_SECONDS` — default `300`
- `APEX_ASSISTANT_URL` — absolute dashboard URL used in Telegram messages
- `APEX_MOBILE_ALERT_DB` — optional SQLite path override

Recommended Render setting:
`APEX_ASSISTANT_URL=https://apex-engine-dashboard.onrender.com/assistant`

## Safety and Execution Governance
- All alerts are advisory.
- Broker execution remains manually confirmation-gated.
- APEX does not place, modify, cancel, or close Power E*TRADE orders.
- Missing/stale data fails closed and suppresses new momentum-entry alerts.
- Duplicate alerts are suppressed by opportunity and alert stage.

## Validation
- Phase 37 focused tests: **8 passed**
- Phase 34–37 compatibility slice: **27 passed**
- Trade Director Phase 13–37 regression suite: **115 passed**
- Python compilation and compile-all: **PASSED**
- Assistant JavaScript syntax: **PASSED**
- Autonomous execution: **DISABLED / UNCHANGED**

## Deployment Notes
1. Deploy the complete repository or copy the changed-files archive while preserving paths.
2. Confirm the Telegram bot token and chat ID are configured in Render.
3. Set `APEX_ASSISTANT_URL` to the deployed `/assistant` URL.
4. Redeploy and use **Send Test Telegram** in the Mobile Operations panel.
5. During market hours, verify that the scanner is running on the desired cadence. Phase 37 can only alert when fresh scans provide current evidence.
