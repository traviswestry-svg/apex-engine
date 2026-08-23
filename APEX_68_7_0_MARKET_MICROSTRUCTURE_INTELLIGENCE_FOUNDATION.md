# APEX 68.7.0 — Market Microstructure Intelligence Foundation

## Why 68.7.0
The supplied baseline already contains APEX 68.6.0 Decision Outcome Attribution & Abstention Effectiveness, so the Bookmap-inspired microstructure work begins at **68.7.0** rather than reusing 68.6.

## Repository capability audit
The existing ES/MES path in `app.py` uses Massive/Polygon **futures aggregate bars** (`/futures/v1/aggs/{ticker}`). That is useful for ES price, overnight structure, aggregate volume and ES/SPX context, but it is not a central-limit-order-book feed.

The repository does **not** currently contain a native adapter for:
- exchange L2/DOM depth,
- market-by-order (MBO),
- add/modify/cancel order events,
- exchange order IDs / sequence IDs,
- aggressor-classified tick trades sufficient for authoritative CVD,
- native iceberg reconstruction.

APEX therefore must not manufacture Bookmap-like evidence from candles or aggregate bars.

## Added
### `engine/market_microstructure.py`
Provider-neutral, observation-only normalized microstructure contract supporting:
- bid/ask depth and depth imbalance,
- spread / BBO,
- liquidity add/pull comparison between snapshots,
- aggressor buy/sell volume and delta when side classification is supplied,
- conservative absorption candidates from execution-vs-price response,
- repeated replenishment / iceberg candidates when order events are supplied,
- explicit readiness and missing-feed governance.

### API
- `GET /api/microstructure/capability`
- `GET /api/microstructure/health`
- `POST /api/microstructure/analyze`

The POST route is an **analysis boundary only**. It cannot place orders or change APEX decisions.

## Canonical instrument roles
- **SPX:** thesis, options positioning, gamma, expected move and 0DTE context.
- **ES:** future L2/MBO microstructure and execution confirmation.

This preserves APEX's SPX-specific decision architecture while using ES as the tradable central-limit-order-book proxy.

## Feed contract required for the next phase
Minimum L2:
- timestamp
- instrument
- side
- price
- size
- incremental add/change/remove or full depth snapshots
- aggressor-classified trades

For high-confidence iceberg reconstruction:
- order ID
- add/modify/cancel/execute event type
- exchange sequence/order
- price and remaining/displayed size

## Safety / calibration governance
68.7.0 is intentionally **shadow/advisory only**:
- `production_effect = NONE`
- `influences_decision = false`
- `execution_authority = false`
- no synthetic DOM from aggregate bars
- no microstructure confirmation score until outcomes can be calibrated

The next implementation wave should connect a real ES depth feed, persist bounded liquidity state, and only then add Spatial Gamma Path × Liquidity and Flow Persistence × Book Interaction evidence.
