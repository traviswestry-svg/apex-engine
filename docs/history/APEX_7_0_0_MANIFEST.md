# APEX 7.0.0 — Institutional Intelligence Platform

Version: `7.0.0_APEX_INSTITUTIONAL_INTELLIGENCE`

## Mission Complete

APEX 7.0 delivers: when the operator opens the terminal, within 5 seconds they know:
- What is moving SPX (Market Drivers)
- What dealers are likely doing (Dealer Positioning)
- Where price may pin (Strike Magnets)
- Whether institutions are aligned (Institutional Intelligence score)
- Whether the auction is accepting value (Auction Intelligence)
- Whether to trade, watch, or avoid (Trade Coach 5.0 + Decision)
- Exactly why (Story Engine 5.0 + Evidence chain)

## Sprint Completion

| Sprint | Status | Description |
|---|---|---|
| 7.0.1 | ✅ | Cleanup — root duplicates removed, VERSION bumped |
| 7.0.2 | ✅ | engine/market_drivers.py — 20 SPX constituents tracked |
| 7.0.3 | ✅ | engine/options_chain.py — GEX-derived chain intelligence |
| 7.0.4 | ✅ | engine/dealer_positioning.py — 7-phase dealer engine |
| 7.0.5 | ✅ | engine/strike_magnet.py — ranked pin level map |
| 7.0.6 | ✅ | engine/flow_intelligence.py — Flow 3.0 with contradiction detection |
| 7.0.7 | ✅ | engine/institutional_intelligence.py — canonical master object v7.0 |
| 7.0.8 | ✅ | engine/story.py — 3 new chapters: Drivers, Dealer, Magnets |
| 7.0.9 | ✅ | engine/trade_coach.py — 5 new institutional fields |

## New Files

| File | Purpose |
|---|---|
| `engine/market_drivers.py` | Tracks 20 SPX constituents, identifies what's moving the index |
| `engine/strike_magnet.py` | Ranks price magnet levels (Call Wall, Put Wall, Gamma Flip, Max Pain) |

## Changed Files

| File | Change |
|---|---|
| `engine/__init__.py` | Added market_drivers and strike_magnets exports |
| `engine/story.py` | Added 3 new chapters + institutional_intelligence param |
| `engine/trade_coach.py` | Added 5 new 7.0 institutional fields |
| `engine/flow_intelligence.py` | Flow 3.0 — contradiction detection, dark pool, intent classification |
| `engine/institutional_intelligence.py` | v7.0 — market_drivers, strike_magnets, evidence chain |
| `app.py` | VERSION 7.0.0, market_drivers + strike_magnets wired, 5 new API endpoints, last_result cache |

## New API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/market_drivers?ticker=SPX` | What's moving SPX — top bullish/bearish drivers |
| `GET /api/strike_magnets?ticker=SPX` | Price magnet map — ranked pin levels |
| `GET /api/dealer_positioning?ticker=SPX` | Full dealer positioning object |
| `GET /api/options_chain_intelligence?ticker=SPX` | Options chain intelligence |
| `GET /api/institutional_intelligence?ticker=SPX` | Canonical 7.0 master object |

## Verification Checklist

```bash
# All should return 200 with ok:true after first scan
curl https://apex-engine-dashboard.onrender.com/health
curl https://apex-engine-dashboard.onrender.com/api/institutional_os?ticker=SPX&heatmap=1
curl https://apex-engine-dashboard.onrender.com/api/institutional_intelligence?ticker=SPX
curl https://apex-engine-dashboard.onrender.com/api/market_drivers?ticker=SPX
curl https://apex-engine-dashboard.onrender.com/api/options_chain_intelligence?ticker=SPX
curl https://apex-engine-dashboard.onrender.com/api/dealer_positioning?ticker=SPX
curl https://apex-engine-dashboard.onrender.com/api/strike_magnets?ticker=SPX
curl https://apex-engine-dashboard.onrender.com/api/flow_tape
curl https://apex-engine-dashboard.onrender.com/api/review/summary
```

## Deployment

```bash
git add engine/market_drivers.py engine/strike_magnet.py \
        engine/flow_intelligence.py engine/institutional_intelligence.py \
        engine/story.py engine/trade_coach.py engine/__init__.py \
        app.py APEX_7_0_0_MANIFEST.md
git commit -m "APEX 7.0.0 — Institutional Intelligence Platform"
git push
```

All new engines are non-fatal — if any fails, pipeline continues with existing output.

## Notes on Data Availability

- `market_drivers`: requires Polygon snapshot endpoint (v2/snapshot/locale/us/markets/stocks)
- `strike_magnets`: uses existing GEX data — no new API calls
- `options_chain`: uses existing GEX strike data — no new API calls
- `institutional_intelligence`: aggregates all existing engine outputs — no new API calls
