# APEX 65.6.4 — Next-Session Brief Integrity Hotfix

## Objective
Correct next-session/pre-market semantic leakage without changing trading, risk, signal, or broker execution logic.

## Changes
1. **Trading-session dates** — `source_session_date` now means the last completed trading session supplying historical context. Weekend and pre-market generation use the prior weekday session; `target_session_date` identifies the session being prepared for.
2. **Future-session OR/IB suppression** — when target and source sessions differ, OR 5m/15m, Initial Balance, and IB extensions are rendered `[FEED REQUIRED]` and excluded from highest-probability ranking. Prior-session opening levels can no longer masquerade as target-session levels.
3. **Settlement integrity** — raw ES previous-session close/settlement proxy is surfaced separately as `prev_settlement_raw_es`. SPX `prev_settlement` remains unavailable unless a valid ES→SPX basis exists; this avoids silently comparing two instruments on different rulers.

## Validation
- Weekend source/target session regression: PASS
- Next-session OR/IB suppression regression: PASS
- 65.6.3 null-contract regressions: PASS
- Python compileall: PASS

## Expected production behavior
For Saturday 2026-08-01 preparing Monday 2026-08-03:
- source_session_date = `2026-07-31`
- target_session_date = `2026-08-03`
- OR/IB rows = `[FEED REQUIRED]`
- OR/IB entries absent from ranked levels
- raw ES settlement proxy may be AVAILABLE as `prev_settlement_raw_es`
- SPX-normalized `prev_settlement` remains missing if basis cannot be observed
