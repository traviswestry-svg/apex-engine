# APEX 18.0.1 — E*TRADE Strategy Execution Parity

## Objective
Extend the SPX Trade Command Center from a single-leg long-option workflow to a broker-neutral, leg-based strategy ticket supporting one through four option legs while preserving explicit human confirmation and the existing E*TRADE trading-enable gate.

## Delivered

- Canonical `ComplexLeg` and `ComplexOrderIntent` models.
- Strategy blueprints for long calls/puts, debit spreads, credit spreads, and Iron Condors.
- Exact contract resolution by side, strike, and expiration.
- Explicit BUY_OPEN / SELL_OPEN display for every leg.
- OCC/OSI key, expiration, DTE, bid, ask, midpoint, delta, IV, volume, open interest, quote age, and source fields.
- Net-credit/net-debit construction and limit-price selection.
- Defined-risk calculations for vertical spreads and Iron Condors.
- Execution blocking when a leg, quote, identifier, expiration, or risk value cannot be validated.
- E*TRADE complex-order preview/place payloads containing all instruments in one order.
- New `Arm Plan → Preview Strategy → Confirm & Submit` mobile workflow.

## Supported recommendation mappings

- Long call
- Long put
- Call debit spread
- Put debit spread
- Call credit spread / bear call spread
- Put credit spread / bull put spread
- Iron Condor

The canonical leg model also provides the foundation for later calendar, diagonal, butterfly, straddle, strangle, covered-call, and custom-combination mappings after those recommendation schemas are defined and E*TRADE payloads are certified.

## Safety contract

- Arm Plan never submits.
- Preview is required before placement.
- Explicit `confirmed=true` is required.
- `ETRADE_ENABLE_TRADING=true` remains required inside the broker adapter.
- Missing or stale leg data blocks preview.
- Complex positions are sent as one multi-instrument order, not separate naked leg orders.
