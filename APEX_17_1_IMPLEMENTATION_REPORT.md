# APEX 17.1 Implementation Report

## Release
APEX 17.1 — Institutional Trading Desk UX

## Objective
Convert the existing collection of institutional engines into one professional, read-only decision workspace without changing recommendation, risk, position, or broker behavior.

## Delivered
- New `engine/institutional_trading_desk_ux.py` aggregation layer.
- New read-only workspace and status APIs.
- Complete Institutional Trading Desk interface redesign.
- Persistent eight-field decision ribbon.
- Institutional briefing and readiness display.
- Evidence Explorer with explicit unavailable states.
- Autonomous Desk lifecycle timeline with evidence drill-down.
- Live Position Monitor and Adaptive Management view.
- Institutional Performance Center.
- Broker Health Center and discrepancy visibility.
- Explainable Intelligence question interface.
- Browser-only workspace preferences.
- Keyboard-accessible command palette (`Ctrl/Cmd + K`).
- Responsive desktop, tablet, and mobile layouts.

## Architecture
The 17.1 layer composes existing governed engine outputs. It does not create a second source of truth and does not mutate the underlying engines.

## Safety
- Human confirmation remains required.
- Automatic broker order submission remains disabled.
- Broker mutation remains disabled.
- Workspace persistence is local to the browser.
- Missing data is displayed as unavailable rather than fabricated.
