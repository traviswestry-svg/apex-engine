# APEX 6.5.0 — Four Pillar Architecture Manifest

Version: `6.5.0_APEX_FOUR_PILLAR`
Date: 2026-07-02

## Architecture

APEX 6.5 organizes all intelligence into four pillars:

| Pillar | Engines | Purpose |
|---|---|---|
| Market Structure | Auction, Volume Profile, Rotation, Trend | What is the market doing? |
| Dealer | GEX, DEX, VEX, CHEX, Hedging, Pinning | What are dealers doing? |
| Institutional | Flow, Options Chain, Story | What do institutions intend? |
| Execution | Pine, Trade Coach, Risk, Replay | What is the trade? |

## New Files

| File | Purpose |
|---|---|
| `engine/options_chain.py` | Options chain intelligence — OI profile, gamma profile, skew, dealer bias |
| `engine/volatility.py` | Volatility intelligence — IV rank, term structure, regime, dealer vega risk |
| `engine/rotation.py` | Market rotation engine — sector leadership, capital flow, relative strength |
| `engine/institutional_intelligence.py` | Canonical master object — single source consumed by all dashboard components |

## Changed Files

| File | Change |
|---|---|
| `engine/__init__.py` | Added 4 new exports |
| `app.py` | VERSION bumped, 4 new engines wired, SCANNER_STATE declared |
| `static/js/apex_os.js` | `renderInstitutionalIntelligence()` added, wired into loadOS |
| `templates/apex_os.html` | Four Pillar Intelligence tab added to analytics card |
| `static/css/apex_os.css` | `.ii-*` styles added |

## API Response — New Fields

`GET /api/institutional_os` now includes:
- `result.institutional_intelligence` — canonical four-pillar object
- `result.options_chain` — options chain intelligence
- `result.volatility` — volatility regime and path
- `result.rotation` — sector rotation and relative strength

## Design Principle

`institutional_intelligence` is the SINGLE object that every dashboard
component reads. No component independently queries multiple engines.
One object, built once per scan, consumed everywhere.

## Deployment

```bash
git add engine/options_chain.py engine/volatility.py engine/rotation.py \
        engine/institutional_intelligence.py engine/__init__.py \
        app.py static/js/apex_os.js templates/apex_os.html \
        static/css/apex_os.css APEX_6_5_0_MANIFEST.md
git commit -m "APEX 6.5.0 — Four Pillar Architecture"
git push
```

Render auto-deploys on push. No new env vars required.
All 6.5 engines are non-fatal — if any fails, the pipeline continues
with the existing 6.4.1 output. Zero downtime risk.
