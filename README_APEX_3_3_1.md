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

---

## 3.3.2 addendum — closest-to-qualifying visibility

`/api/diagnostics` no longer reports `latest_score_breakdown` (which only had
data when an idea actually qualified, so on a 0-idea scan it was always null
and told you nothing). It now returns `closest_to_qualifying`: the top 10
analyzed tickers by `final_score`, sorted descending, with the full score
breakdown and `excluded_reason` for each, regardless of whether they cleared
`MIN_FINAL_SCORE`. The dashboard's empty state also now lists these directly
so you don't have to leave the page to see how close things are getting.

---

## 3.3.3 addendum — sessionDate fix (the likely real cause of 0 ideas)

The `closest_to_qualifying` debug data from 3.3.2 showed `flow_score`,
`order_flow_score`, `dark_pool_score`, and `catalyst_score` pinned at exactly
`50.0` (the neutral fallback) for every single ticker, while the breaker
showed zero failures -- meaning the calls succeeded but came back empty.
`dark_pool_levels_score` was the only QuantData-derived score with real
variation, and it's also the only one of the five that doesn't compute an
explicit `sessionDate`.

`last_market_date()` correctly identifies the latest weekday (calendar-correct),
but that doesn't guarantee QuantData has finished finalizing that session's
data on their end -- particularly for an off-hours/weekend request. QuantData's
own docs state the default behavior for an omitted `sessionDate` is "the latest
completed trading session," which is QuantData's own judgment call, not ours.

Removed the explicit `sessionDate` from all four affected payloads (net-flow,
order-flow-consolidated, dark-flow, news/tool/articles) so QuantData resolves
it themselves instead of us guessing a date they might not have ready yet.

Run `/api/run` then `/api/diagnostics` after this deploys -- if
`closest_to_qualifying` shows non-50.0 flow/order-flow/dark-pool/catalyst
scores with real spread between tickers, this was it.

Separately: `catalyst_score` being stuck at 50.0 across the board could also
be partly explained by the Massive Benzinga news route (`/benzinga/v2/news`
on the Polygon host) returning nothing -- that's a guessed endpoint path that
hasn't been confirmed against Polygon's actual Benzinga integration docs.
Worth checking Render logs for `GET .../benzinga/v2/news failed` lines; if
present, that route may need to be confirmed/corrected separately, though the
Polygon reference-news fallback in the same function should still cover it.
