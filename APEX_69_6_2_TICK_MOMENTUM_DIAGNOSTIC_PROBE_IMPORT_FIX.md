# APEX 69.6.2 — Tick Momentum Diagnostic Probe Import Fix

Fixes the production `NameError: name 'urlparse' is not defined` in the app-layer diagnostic HTTP transport by importing `urlparse` from `urllib.parse`.

This patch is intentionally narrow. It does not change RTH ingestion, evidence eligibility, persistence, learning, decisions, or execution authority. The diagnostic probe remains non-ingesting and observational only.

## Guardrails
- Diagnostic probe only.
- No evidence ingestion.
- No snapshot/state persistence from the probe.
- No decision influence.
- No execution authority.
- No API-key or authorization-header exposure.
