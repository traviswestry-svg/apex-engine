# APEX 22.0 Market Memory Reference

| Variable | Default | Purpose |
|---|---:|---|
| `APEX_MARKET_MEMORY_DB` | `apex_market_memory.db` | Isolated SQLite memory-store path. Use a Render persistent-disk path before enabling capture. |
| `APEX_MARKET_MEMORY_CAPTURE_ENABLED` | `false` | Unlocks explicit snapshot capture. |
| `APEX_MARKET_MEMORY_OUTCOME_WRITES_ENABLED` | `false` | Separately unlocks outcome attachment. |
| `APEX_MARKET_MEMORY_MIN_SESSIONS` | `20` | Minimum observations before readiness can be reported. |

## Stored feature classes
Ticker/session, market regime, decision/bias, opening type, auction state, value and POC migration, dealer regime/bias, flow bias, overnight structure, strategy family, confidence, day-type probabilities, SPX/VIX, POC/VAH/VAL, and expected move.

Raw API responses, account identifiers, OAuth material, API keys, bot tokens, webhook secrets, and broker tokens are not stored.
