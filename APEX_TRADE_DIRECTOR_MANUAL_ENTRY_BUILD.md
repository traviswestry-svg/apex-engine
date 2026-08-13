# APEX Trade Director — Manual Entry & Management Build

## What changed

The existing Active Trade Director can now be explicitly told when a Power E*TRADE position has filled.

### Operator workflow

1. Open `/assistant`.
2. Click **I'M IN**.
3. Enter CALL/PUT, contracts, SPX entry level, optional SPX stop/targets, option premium, and option symbol.
4. Click **Start Trade Director**.
5. APEX immediately treats the trade as a confirmed manual position and switches to active management.

### Live management actions

The active-position bar supports:

- Trim 25%
- Trim 50%
- Move stop to breakeven
- Mark closed
- Clear APEX position state

These controls update APEX position truth only. They do **not** send orders to E*TRADE.

### Safety and architecture

- No additional startup workers, scanners, or external requests were added.
- The known-good Render stability environment remains unchanged.
- Broker execution remains external and confirmation-gated.
- Existing Active Trade Director tests continue to pass.

## API additions

### POST `/api/position`

Accepts:

```json
{
  "ticker": "SPX",
  "side": "CALL",
  "quantity": 3,
  "entry_price": 6350.25,
  "option_entry_price": 12.45,
  "stop": 6346.00,
  "target1": 6356.00,
  "target2": 6362.00,
  "option_symbol": "SPXW ..."
}
```

### POST `/api/position/action`

Supported actions:

- `TRIM_25`
- `TRIM_50`
- `TRIM_75`
- `MOVE_STOP_BE`
- `CLOSE`

The response explicitly states that no broker order was sent.
