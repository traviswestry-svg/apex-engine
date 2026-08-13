# APEX 6.4.0 — APEX Terminal 1.0 Manifest

**Version:** 6.4.0_APEX_TERMINAL_1_0  
**Date:** 2026-06-28  
**Baseline:** 6.3.0_VOLUME_PROFILE_AUCTION_ENGINE

## Changed Files

| File | Sprint | Change |
|------|--------|--------|
| `app.py` | 6.3.2–6.4.0 | VERSION bump; new imports; flow tape fetch + endpoint; story/coach v3 injection; replay frame recording; replay/review endpoints; review DB init |
| `engine/__init__.py` | 6.3.2–6.3.5 | Added exports: build_flow_tape, build_story_v3, build_trade_coach_v3 |
| `engine/flow_tape.py` | 6.3.2 | NEW — Institutional Flow Tape Engine |
| `engine/story.py` | 6.3.4 | UPGRADED — Story Engine 3.0 (build_story_v3) |
| `engine/trade_coach.py` | 6.3.5 | UPGRADED — Trade Coach 3.0 (build_trade_coach_v3) |
| `static/js/overlays.js` | 6.3.3 | UPGRADED — toggle groups, HVN/LVN arrays, viewport preservation |
| `static/js/apex_os.js` | 6.3.2–6.4.0 | Flow tape render/filter; overlay toggle wiring; review form; replay date picker; trade history |
| `static/css/apex_os.css` | 6.3.2–6.4.0 | Flow tape table/filter; overlay toggle buttons; review form; replay date input |
| `templates/apex_os.html` | 6.3.2–6.4.0 | Flow tape panel; overlay toggle card; upgraded Replay tab with date picker; upgraded Review tab with form |

## Unchanged Files (verified working)
- `apex_engines.py` — no changes; v3 story/coach injected at app.py level
- `engine/volume_profile.py` — no changes (6.3.0)
- `engine/auction.py` — no changes (6.3.1)
- `engine/gamma.py`, `engine/data_bus.py`, `engine/diagnostics.py` — no changes
- `engine/confidence.py`, `engine/execution.py`, `engine/flow_intelligence.py` — no changes
- `engine/market_regime.py`, `engine/ribbon.py`, `engine/risk.py` — no changes
- `engine/structure.py`, `engine/trend.py` — no changes
- `static/js/chart_engine.js`, `chart_sync.js`, `crosshair.js`, `viewport.js` — no changes
- `static/css/charts.css` — no changes
- `templates/chart.html`, `dashboard.html`, `flow.html`, `assistant.html` — no changes
- `render.yaml`, `requirements.txt`, `runtime.txt` — no changes

## Compile Check
```
python -m py_compile app.py apex_engines.py engine/*.py
# Result: ALL CLEAR — zero errors
```

## New Endpoints
| Endpoint | Method | Sprint |
|----------|--------|--------|
| /api/flow_tape | GET | 6.3.2 |
| /api/replay/session | GET | 6.4.0 |
| /api/replay/frame | GET | 6.4.0 |
| /api/review/trade | POST | 6.4.0 |
| /api/review/trades | GET | 6.4.0 |
| /api/review/summary | GET | 6.4.0 |

## Preserved Endpoints (unchanged)
/health · /apex_os · /chart · /flow · /assistant · /scanner  
/api/status · /api/run · /api/scanner_ideas · /api/institutional_os  
/api/market_state · /api/charts/state · /api/diagnostics/gamma  
/api/confidence_timeline · /api/volume_profile · /api/auction_state
