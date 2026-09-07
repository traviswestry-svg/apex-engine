# APEX 44.0 — Institutional Liquidity Intelligence Engine

## Added
- Ranked liquidity map: PDH/PDL, ONH/ONL, VAH/VAL/POC, gamma walls, expected move, swing/equal levels, and round numbers.
- Dynamic 0–100 strength and reaction expectation for every active pool.
- Institutional intent classification: accumulation, distribution, short covering, long liquidation, or neutral.
- Real-time buy-side/sell-side sweep continuation versus failed-sweep classification.
- Liquidity Race now selects the strongest active opposing pools, not merely the first supplied levels.
- Trade Director advisory context with target-side, intent alignment, sweep state, and eligibility gate.
- SQLite outcome memory and calibration summary endpoint.

## API
- `GET|POST /api/liquidity-intelligence`
- `GET /api/liquidity-intelligence/memory`
- Existing `GET|POST /api/liquidity-race` remains compatible.

## Safety
- Advisory only. No order placement or modification authority.
- Displayed/resting size remains low-weighted.
- Contact with liquidity is not treated as proof of breakout; absorption must be reassessed.
