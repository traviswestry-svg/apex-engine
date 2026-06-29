# APEX 6.3.4 Changelog — Story Engine 3.0

**Sprint:** 6.3.4  
**Date:** 2026-06-28  
**Status:** Production

## Changes

### engine/story.py (UPGRADED — full rewrite)
- `build_story_v3()` — 10-chapter institutional narrative
- New Chapter 3: Auction / Volume Profile
  - POC price vs. current price
  - Value area location (inside / above VAH / below VAL)
  - POC migration direction (rising/falling/stable)
  - Auction narrative from engine
- New Chapter 5: Institutional Flow Tape
  - Tape bias (BULLISH / BEARISH / MIXED)
  - Net premium
  - Sweep / block counts
  - Aggressive call/put sweep callouts
- Session-aware labels: [PRE-MARKET] / [AFTER-HOURS] / [CLOSED SESSION]
- POC/VWAP confluence detection in Market Structure chapter
- Richer executive summary: includes POC location and tape bias when available
- `has_auction_chapter` and `has_tape_chapter` flags in response
- Legacy shim re-exports `engine_story` / `build_story_timeline` from apex_engines

### apex_engines.py — NOT changed
- Story 3.0 is injected at the /api/institutional_os level, after apex_engines runs
- apex_engines.py story (v2) serves as fallback if story_v3 fails

### app.py — Story 3.0 Integration
- `build_story_v3()` called in /api/institutional_os after nine-engine pipeline
- Session state forwarded from market_session_context()
- auction, volume_profile, flow_tape_summary passed to story engine
- Story v3 result replaces story v2 in the API response

## Chapter Order (by significance)
1. Market Regime (1.0)
2. Gamma Regime (1.5)
3. Trend (1.8)
4. Auction / Volume Profile (2.0)
5. Market Structure (2.0)
6. Institutional Flow Intelligence (2.5)
7. Institutional Flow Tape (2.7) [if rows available]
8. Pine Execution (3.0)
9. Divergence / Absorption (if present)
10. Institutional Verdict (4.0)
