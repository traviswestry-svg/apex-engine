# APEX 15.0 Sprint 15.2 — Institutional Playbook Engine

## Purpose
IPE deterministically maps decision-time market evidence and immutable IMSE context to a governed SPX playbook. It is an advisory, read-only intelligence layer.

## Delivered
- `engine/institutional_playbook_engine.py`
- 20-playbook governed library across Trend, Auction, Gamma, Volatility, Flow, and Reversal families
- Deterministic playbook recognition and ranking
- Playbook Quality Score and IMSE compatibility score
- Immutable playbook records and transitions
- Descriptive historical outcome statistics isolated from live selection
- REST APIs and `/apex_os/playbook_engine` dashboard
- Decision Intelligence Center integration
- Institutional Replay 2.0 integration
- Cross-Examination `PLAYBOOK` intent

## APIs
- `GET /api/playbooks/status`
- `GET /api/playbooks/library`
- `POST /api/playbooks/evaluate`
- `POST /api/playbooks/record`
- `GET /api/playbooks/current`
- `GET /api/playbooks/history`
- `GET /api/playbooks/transitions`
- `GET /api/playbooks/statistics`
- `GET /api/playbooks/dashboard`

## Safety
IPE does not alter recommendations, confidence, conviction, risk, execution, champion selection, canary routing, or governance. It uses no future information and completed outcomes do not feed live selection.
