# APEX 16.1 — Live Mission Control Implementation Report

## Scope
APEX 16.1 adds a unified institutional command surface on top of APEX 16.0. The centerpiece remains Institutional Order Flow Intelligence 2.0, now composed with IMSE, the Institutional Playbook Engine, current decision evidence, structure context, and an advisory position monitor.

## Implemented
- `engine/live_mission_control.py`
- Deterministic Institutional Confluence Score (ICS)
- Eight explicitly weighted confluence inputs
- Directional agreement penalty and evidence coverage
- A+/A/B+/B/C/STAND_DOWN setup grading
- Evidence-grounded institutional briefing
- Read-only live position monitor
- Mission Control status, dashboard, and confluence APIs
- `/apex_os/mission_control` dashboard alias
- Rebuilt Institutional Trading Desk page as Live Mission Control

## Institutional Confluence Inputs
- Institutional Pressure Score
- Pressure conviction
- IMSE confidence
- IMSE stability
- Playbook Quality Score
- Playbook/IMSE compatibility
- Decision confidence
- Structure alignment

## Safety
Mission Control is a deterministic, read-only composition layer. It does not change recommendations, confidence, market state, playbook selection, risk, positions, or broker orders.
