# APEX 6.3.5 Changelog — Trade Coach 3.0

**Sprint:** 6.3.5  
**Date:** 2026-06-28  
**Status:** Production

## Changes

### engine/trade_coach.py (UPGRADED — full rewrite)
- `build_trade_coach_v3()` — full decision assistant

#### New inputs consumed:
- `auction` — auction state (POC, VAH, VAL, poc_migration, auction_state)
- `volume_profile` — volume profile levels
- `flow_tape_summary` — tape bias, net premium, sweep count

#### New outputs:
- `readiness` (0–100) — percentage of checklist items met
- `invalidation` — computed stop/invalidation level from POC/VWAP if risk module stop is null
- `scale_out_plan` — list of scale-out steps (T1 50%, T2 remainder, Wall targets)
- `checklist` — 7-item confirmation checklist with met/unmet status
- `entry_note` — context-aware entry note (POC/VWAP pullback guidance)
- `poc`, `vah`, `val`, `vwap` — convenience fields for UI
- `poc_migration`, `auction_state`, `tape_bias`, `tape_sweeps` — context fields

#### New blockers:
- Price below VAL when watching calls (not accepting higher)
- Price above VAH when watching puts (not accepting lower)
- Flow tape shows opposing sweep aggression

#### Action narrative by state:
- ENTER_CALL/ENTER_PUT: "Enter [side] now. Entry [zone]. Stop $X. T1 $Y, T2 $Z."
  + POC location + sweep confirmation
- READY: "Setup ready. Wait for Pine confirmation. {entry_note}"
- WATCH_CALLS/WATCH_PUTS: "Watch [side]. {entry_note} Confirm Pine before entering."
- NO_TRADE: "No trade. {top 2 blockers}."

### app.py — Trade Coach 3.0 Integration
- `build_trade_coach_v3()` called after Story 3.0 in /api/institutional_os
- auction, volume_profile, flow_tape_summary passed in
- Result replaces trade_coach v2 in API response
- Falls back to v2 coach if v3 raises

### engine/__init__.py
- Exports `build_story_v3`, `build_trade_coach_v3`
