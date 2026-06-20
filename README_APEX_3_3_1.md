# APEX 3.3.1 — QuantData Schema Fixes

Your Render logs from the 3.3 deploy confirmed the timing/concurrency fix worked
(single worker, ~6-7s scans, breaker engaging correctly). But they also surfaced
a real `400 ValidationFailure` from QuantData on every dark-pool-levels call,
which led to checking the engine's QuantData integration against QuantData's
actual published API docs (quantdata.us/api/docs). Found three real schema
mismatches — these were silently degrading every single scan to neutral scores
on the highest-weighted layers, which is the more likely explanation for
`"Qualified ideas: 0"` on every cycle than market conditions alone.

## 1. Dark Pool Levels — wrong request shape (the one that errored in your logs)

QuantData's docs require a top-level `sessionDateRange.startDate`. The engine
was sending `sessionDate`, which doesn't exist for this endpoint — hence the
400 on every ticker, every scan. Fixed to send
`{"sessionDateRange": {"startDate": ...}, "filter": {...}}` with a 10-day
lookback window (`DARK_POOL_LEVELS_LOOKBACK_DAYS`, configurable).

Separately, the response shape for this endpoint is an object keyed by price
level (e.g. `"217.50": {"notionalValue": ..., "size": ..., "tradeCount": ...}`)
— not a list of rows with a `price` field. Even with the payload fixed, the old
parsing code would never have found a level, because it was looking for a field
that doesn't exist instead of reading the dict key. Both are fixed now.

## 2. Net Flow — premium units were cents, not dollars

QuantData's docs state `NET_PREMIUM` mode returns `callSum`/`putSum` in cents.
The engine was treating the raw number as dollars, which made the `total /
5,000,000` size-boost in the flow score effectively dead weight (a real $5M of
premium showed up as $50K to the formula). Now divides by 100 before scoring.
This was feeding into the single highest-weighted score component (28% of
final score, 35% of accumulation score), so this alone could plausibly have
been suppressing most setups below `MIN_FINAL_SCORE`.

## 3. Order Flow Consolidated — classification fields didn't exist on the real schema

The sweep/block/sentiment detection searched row keys `side`, `sentiment`,
`tradeSide`, `classification`, `type`, `executionType` — none of which exist on
this endpoint. The real fields are `tradeSideCode` (`ABOVE_ASK` / `AT_ASK` /
`AT_BID` / `BELOW_BID`) and `tradeConsolidationType` (`SWEEP` / `BLOCK` /
`SPLIT`). Practically, this meant `sweep_count` and `block_count` were always
0, and direction silently fell back to a plain call/put split with no real
sentiment signal. Rewired to the documented field names.

## Verification

All three were unit-tested against synthetic payloads built directly from
QuantData's own documented example responses (not guessed) — see the test
script run during development; each one is confirmed parsing correctly before
this package was built.

## What to watch after this deploys

Check `/api/diagnostics` → `latest_score_breakdown` on the next scan and
compare `flow_score` / `order_flow_score` / `dark_pool_levels_score` to what
you were seeing before. If ideas still aren't qualifying, that's now much more
likely to be genuine market conditions (or `MIN_FINAL_SCORE=78` being a high
bar) than broken data feeding the model.
