# APEX 66.5 — Canonical Event Integrity Fix

## Problem
Institutional OS correctly identified CPI (Jul) on 2026-08-12 while Morning Readiness could state that no scheduled macro/economic catalysts were provided.

## Root cause
Morning Readiness did not include `engine.event_calendar` in its deterministic model context. Its Section 2 could therefore be authored independently by the AI narrative and cached, allowing it to contradict the deterministic Event Intelligence used elsewhere in APEX.

## Fix
- Morning Brief/Readiness now consumes `engine.event_calendar.build_event_intelligence()` as its canonical scheduled-event contract.
- The canonical event state is injected into the model context as `scheduled_events`.
- Section 2 is deterministically rendered from the canonical contract and replaces any conflicting AI-generated Section 2, including cached narrative.
- When event intelligence is unavailable, the page states `EVENT DATA UNAVAILABLE`; it may not convert missing evidence into a claim that no events exist.
- The API now exposes `scheduled_events` and `event_integrity` diagnostics.
- The structured payload also carries `scheduled_events` so downstream consumers can use the same state.

## Validation
- New canonical-event tests: 3/3 passed.
- Morning Brief regression subset: 12/12 passed.
- Python compilation passed.
