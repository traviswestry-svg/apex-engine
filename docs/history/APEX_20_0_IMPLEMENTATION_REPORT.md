# APEX 20.0 Implementation Report

## Release identity
- Application: APEX 20.0 — Institutional Decision Engine
- Runtime: `13.0.0_INSTITUTIONAL_DECISION_ENGINE`
- Semantic version: `13.0.0`
- Baseline: user-supplied APEX 19.2–19.5 repository
- Database migration: not required

## Implementation
APEX 20.0 adds a read-only evidence-fusion layer over the existing Institutional Market Structure, Dealer Positioning, Options Flow Intelligence, Probability, and Adaptive Learning v2 engines. It provides one governed decision object with directional bias, regime, confidence, evidence coverage, disagreement reporting, scenario probabilities, an operator narrative, institutional levels, and an advisory options-strategy family.

The engine makes no network calls and performs no broker previews, submissions, cancellations, replacements, or mutations. Existing execution permissions remain authoritative.

## APIs
- `GET /api/institutional-decision/status`
- `GET /api/institutional-decision/diagnostics`
- `GET /api/institutional-decision/scenarios`
- `GET /api/institutional-decision/evidence`
- `GET /api/institutional-decision/strategy`

## Mission Control
A compact Institutional Decision Engine panel displays decision state, bias, conviction, regime, headline, and links to diagnostics, scenarios, evidence, and strategy.

## Safety contract
- Read-only intelligence
- Automatic execution remains disabled
- Broker mutation remains disabled unless governed elsewhere
- Human confirmation remains required
- Existing global kill switch remains authoritative
- Stale data, inadequate evidence, neutral edge, or inadequate confidence fail closed
- Strategy output is advisory and requires live option-chain validation
