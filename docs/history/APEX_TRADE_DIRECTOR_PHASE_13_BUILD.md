# APEX Trade Director Phase 13

## Cross-Asset Intelligence & Lead-Lag Engine

Phase 13 adds a cached-only intermarket confirmation layer for SPX. It reads the existing APEX `STATE.last_result` cache and Active Trade Director output. It never starts a scanner, requests provider data, opens a broker connection, or transmits an order.

### Intelligence produced

- SPX confirmation score from 0–100
- Cross-asset bullish, bearish, or neutral bias
- ES/NQ/SPY/QQQ/VIX/breadth/HYG/DXY/US10Y/XLK/XLF signal matrix
- Lead and lag market detection
- High- and medium-severity divergence alerts
- Cross-asset regime classification
- Rates → dollar → NQ → ES → SPX → options-flow transmission map
- Trade Health adjustment and sizing posture advisory
- Historical cross-asset comparable sessions through Phase 12 archives

### Endpoint

`GET /api/position/cross-asset-intelligence`

The endpoint is read-only and uses cached data. Missing instruments are explicitly returned as unavailable rather than fabricated.

### Phase 12 archive enrichment

New deliberate Phase 12 archives can include:

- `cross_asset_regime`
- `spx_confirmation_score`
- `cross_asset_bias`

No new environment variable is required for Phase 13.

### Safety

Phase 13 is advisory. Phase 9 risk readiness and Phase 10 confirmation-gated execution remain authoritative.
