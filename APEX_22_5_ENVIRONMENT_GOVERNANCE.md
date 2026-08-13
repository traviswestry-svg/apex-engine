# APEX 22.5 Environment Governance Additions

| Variable | Category | Type | Default | Safety critical | Purpose |
|---|---|---:|---|---:|---|
| `APEX_EXECUTION_TICK_SIZE` | EXECUTION | number | `0.05` | Yes | Advisory execution price increment |
| `APEX_MAX_TOTAL_OPEN_RISK` | RISK | number | unset | Yes | Aggregate open-risk ceiling |
| `APEX_PREMIUM_EXECUTION_ENABLED` | EXECUTION | boolean | `false` | Yes | Premium execution eligibility flag; existing safety controls remain authoritative |
| `PREMIUM_ELIGIBILITY_THRESHOLD` | RISK | number | unset | Yes | Premium strategy confidence threshold |
| `TRADE_MAX_DAILY_LOSS` | RISK | number | unset | Yes | Daily loss lockout threshold |
| `TRADE_MAX_TRADES_PER_DAY` | RISK | integer | unset | Yes | Daily trade limit |
| `TRADE_LOSS_LOCKOUT_COUNT` | RISK | integer | unset | Yes | Consecutive-loss lockout count |
| `APEX_SCANNER_LEASE_PATH` | SCANNER | string | `/tmp/apex_scanner.lock` | No | Single scanner-owner process lease |
| `APEX_PERSISTENT_DISK_PATH` | DATABASE | string | unset | No | Operator-declared persistent storage root |
| `RENDER_DISK_PATH` | DEPLOYMENT | string | platform-provided | No | Render persistent disk mount metadata |

Market Memory variables from APEX 22.0 are now correctly present in the authoritative registry after fixing the registry construction-order defect.
