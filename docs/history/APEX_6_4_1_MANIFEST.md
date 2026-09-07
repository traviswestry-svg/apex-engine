# APEX 6.4.1 Manifest — Consolidation Sprint

**Version:** 6.4.1_APEX_TERMINAL_CONSOLIDATION  
**Date:** 2026-06-28

## Changed Files

| File | Sprint | Type |
|------|--------|------|
| `engine/market_state.py` | 6.4.1 | NEW |
| `engine/story.py` | 6.4.1 | REWRITE |
| `engine/trade_coach.py` | 6.4.1 | REWRITE |
| `engine/__init__.py` | 6.4.1 | EXPORT added |
| `app.py` | 6.4.1 | WIRING — canonical state, enriched replay |
| `static/js/apex_os.js` | 6.4.1 | renderCoachSnapshot, loadReplayFrame |
| `static/css/apex_os.css` | 6.4.1 | Coach 3.1 + replay styles |

## Compile Check
```
python -m py_compile app.py apex_engines.py engine/*.py
ALL CLEAR
```

## Verification
| Endpoint | Expected |
|----------|----------|
| GET /health | ok: true |
| GET /apex_os | Terminal loads |
| GET /api/institutional_os?ticker=SPX | market_state field present in response |
| GET /api/institutional_os?ticker=SPX | story.engine == "STORY_3.1" |
| GET /api/institutional_os?ticker=SPX | trade_coach.scale_out_plan present |
| GET /api/institutional_os?ticker=SPX | trade_coach.dont_trade_if present |
| GET /api/institutional_os?ticker=SPX | trade_coach.checklist present |
| GET /api/replay/frame?ticker=SPX&date=YYYY-MM-DD&time=HH:MM | executive_summary present in frame |
| GET /api/volume_profile?ticker=SPX | unchanged |
| GET /api/auction_state?ticker=SPX | unchanged |
| GET /api/flow_tape | unchanged |

## Deployment
```bash
git add -A
git commit -m "APEX 6.4.1 — Consolidation: canonical state, Story 3.1, Coach 3.1"
git push
```
No new env vars. No DB schema changes.
