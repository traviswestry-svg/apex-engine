# APEX — Data API Utilization Audit (Phase 0)

> **Scope & honesty note.** The *code-side* findings below are extracted from the
> repository snapshot (`apex-engine-main.zip`), not the live Render deployment — if
> the two have drifted, this reflects the snapshot. The *plan* column comes from
> your subscriptions screenshot. The *cost / rate-limit / exact-entitlement*
> figures that only your provider dashboard can give are marked **[YOU FILL IN]** —
> I have not invented them.
>
> **Key structural finding up front:** your code talks to **`api.polygon.io`**, and
> Massive is a Polygon-compatible API (identical endpoint structure — that's why
> the Massive docs mirror Polygon's). So "Massive utilization" = "how the code uses
> the Polygon-shaped REST API." Everything below applies whether the backing host
> is Polygon or Massive.

---

## 1. Providers in use (from code) vs plans you pay for (from screenshot)

| Provider (host) | Used by APEX for | Your plan (screenshot) | Monthly |
|---|---|---|---|
| **Polygon/Massive** `api.polygon.io`, `futures.polygon.io` | equity aggregates, options chain/snapshots, indices, futures (ES), grouped daily, news, VIXY | Indices Advanced, Options Advanced, Futures Starter, Stocks Starter | $99 + $199 + $29 + $29 |
| **QuantData** `api.quantdata.us` | options flow: net-flow, order-flow consolidated, dark-pool levels, dark-flow | *(not on screenshot — separate)* | [YOU FILL IN] |
| **Benzinga** `api.benzinga.com` | news / catalysts | Benzinga News | $99 |
| **E\*TRADE** `api.etrade.com` / `apisb.etrade.com` | order lifecycle (preview/place/change/cancel), portfolio, accounts | brokerage (not a data plan) | — |
| **Telegram** `api.telegram.org` | alert notifications | — | — |
| **Currencies Basic** | *(no forex calls found in code)* | Currencies Basic | $0 |

**Immediate observations:**
- **Currencies Basic ($0)** — no forex endpoints are called anywhere in the code.
  Harmless (it's free), but it's an unused entitlement.
- **Stocks Starter ($29)** — the grouped-daily + equity-snapshot calls (mega-cap
  drivers) use this. Confirm the driver universe size fits Starter's limits
  **[YOU FILL IN: Stocks Starter rate limit]**.
- **Options Advanced ($199)** — your most expensive data plan, and the one whose
  entitlements are most under-used (see §4: snapshot consolidation).

---

## 2. Endpoints the code actually calls

### Polygon/Massive REST
| Endpoint | Purpose | Plan needed |
|---|---|---|
| `/v2/aggs/ticker/{t}/range/{mult}/minute/...` | intraday bars (SPX proxy, tickers) | Indices/Stocks |
| `/v2/aggs/ticker/{t}/range/1/day/...` | daily bars | Indices/Stocks |
| `/v2/aggs/grouped/locale/us/market/stocks/{date}` | **whole-market daily** (driver breadth) | Stocks |
| `/futures/v1/aggs/{front_month}` | ES overnight bars | Futures Starter |
| `/v3/snapshot/options/{ticker}` | options chain snapshot | Options Advanced |
| `/v3/snapshot/options` | multi-contract options snapshot | Options Advanced |
| `/v3/snapshot` | universal snapshot | (tier-dependent) |
| `/v2/snapshot/locale/us/markets/stocks/tickers` | bulk equity snapshot | Stocks |
| `/v2/snapshot/.../tickers/VIXY` | VIX proxy | Stocks |
| `/v3/reference/options/contracts` | contract discovery | Options Advanced |
| `/v2/reference/news` | news | (with plan) |

### QuantData REST
`/v1/options/tool/net-flow`, `/v1/options/tool/order-flow/consolidated`,
`/v1/equities/tool/dark-pool-levels`, `/v1/equities/tool/dark-flow`

### E\*TRADE REST
`/v1/market/optionchains`, `/v1/market/optionexpiredate`, `/v1/accounts/*`
(portfolio, orders preview/place/change/cancel)

---

## 3. THE headline finding: everything is polling REST — zero WebSocket

**The code contains no WebSocket connections.** Every data feed — flow, dealer,
chart, tape, drivers — is REST polling on timers:

- **Backend scan cycle:** `SCAN_INTERVAL_SECONDS = 300` (5 min default), each cycle
  re-fetches its data set via REST.
- **Frontend pollers:** `setInterval` at 5s ×1, 30s ×2, 45s ×1, 60s ×2.

Massive/Polygon **offers a WebSocket API** (confirmed in the docs) for live
trades/quotes/aggregates. APEX uses **none of it**. This is the single largest
optimization opportunity and it's exactly what your Phase 0 predicted:

- **Latency:** a 0DTE tape read on a 5-min REST cycle is structurally stale.
  WebSocket pushes updates in real time.
- **Cost/quota:** repeated REST polling burns request quota that a single
  persistent WebSocket subscription would not.
- **The panel-flicker bug you hit earlier** (3.8s scan cycle, "Scanner load failed")
  is a symptom of REST polling contention — WebSocket would sidestep it.

---

## 4. Redundancy & consolidation opportunities (code-side, real)

1. **Options snapshot fan-out.** Options data is fetched in three places
   (`engine/options/polygon_chain.py`, `app.py`, and E\*TRADE's `optionchains`).
   Confirm these aren't fetching overlapping chains in the same cycle. Polygon's
   **`/v3/snapshot/options/{underlying}`** returns the *whole chain with Greeks/IV/OI
   in one call* — if any code path loops per-contract instead, collapse it to one
   snapshot. **(Options Advanced already entitles you to this — likely under-used.)**

2. **Per-ticker aggregates vs grouped-daily.** Driver breadth uses
   `/v2/aggs/grouped/...` (good — one call for the whole market). Verify the
   mega-cap driver loop isn't *also* making per-ticker `/v2/aggs/ticker/...` calls
   for names already in the grouped response. If it is, that's pure redundancy.

3. **Universal snapshot.** `/v3/snapshot` can return mixed asset types in one call.
   If SPX + VIX + ES + drivers are fetched as separate REST calls each cycle, a
   single universal snapshot may replace several.

4. **VIX via VIXY snapshot.** VIX is proxied through a VIXY equity snapshot. If
   Indices Advanced entitles a direct index value for VIX, that's a cleaner, one
   fewer stocks-plan call **[YOU FILL IN: does Indices Advanced include $VIX?]**.

---

## 5. Utilization report (the table your Phase 0 asked for)

| Dimension | Finding |
|---|---|
| **Endpoints used** | ~11 Polygon/Massive REST paths, 4 QuantData, E\*TRADE order+chain, Benzinga news |
| **Endpoints available but unused** | **WebSocket API (entirely)**; Forex (Currencies plan, $0, unused); likely other Options Advanced snapshot/Greeks endpoints you're entitled to. Full "available" list needs the plan entitlement pages **[YOU FILL IN]** |
| **Polling frequency** | Backend 300s scan; frontend 5/30/45/60s timers; **no push/streaming** |
| **Estimated API cost / quota use** | Requires per-call quota + plan limits **[YOU FILL IN from Massive dashboard]** |
| **Recommended optimizations** | See §6, ranked |

---

## 6. Recommended optimizations — ranked by value-over-risk

1. **Consolidate options fetching to one snapshot per cycle** (LOW risk, immediate
   quota + latency win). You already pay for Options Advanced; use its whole-chain
   snapshot instead of any per-contract looping. Pure win, no new spend.
2. **Kill any grouped-vs-per-ticker redundancy** in driver breadth (LOW risk).
3. **Move the live feeds (flow tape, chart, dealer) to WebSocket** (HIGH value,
   MEDIUM-HIGH effort). This is the big one — real-time instead of 5-min-stale, and
   it removes polling contention. Do it feed-by-feed (strangler pattern), not big-bang.
   Start with the one feed where staleness hurts most (flow tape).
4. **Universal-snapshot the per-cycle market reads** (MEDIUM value/effort) — fewer
   REST round-trips per scan.
5. **Verify VIX source** (LOW) — direct index vs VIXY-proxy.

---

## 7. What only you can complete (provider dashboard)

To finish the true "Massive Utilization Report," pull from your Massive dashboard
and fill the **[YOU FILL IN]** cells:
- Exact endpoint entitlements per plan (Options Advanced, Indices Advanced, Futures
  Starter, Stocks Starter) — the "available but unused" list.
- Per-call / monthly quota and current consumption — the cost column.
- Rate limits per plan — to confirm the driver universe and options fan-out fit.
- Whether your Massive plans include the **WebSocket** entitlement (the docs show
  the API exists; your plan determines access) — this decides whether
  recommendation #3 is free or needs an upgrade.

---

## 8. Honest bottom line on sequencing

Your Phase-0 instinct is right that this establishes a baseline, and the WebSocket
finding is a real, high-value discovery. **But** two caveats:

- The **highest-value item (#3 WebSocket)** is also the **highest-effort**, and it
  only pays off if latency/quota is actually biting. If your 5-min scans are fine
  and you're not near rate limits, the low-risk wins (#1, #2) are worth doing now;
  #3 is worth doing *when* real-time matters (i.e., closer to live trading) or *if*
  polling contention keeps causing the flicker bug.
- This is optimization of a system whose **edge is still unvalidated**. Faster,
  cheaper stale data is still unvalidated data. The audit is genuinely useful and
  the quick wins are cheap — but it doesn't change that the top constraint remains
  outcome data accumulating (see `BACKLOG.md`).

Do #1 and #2 now (cheap, safe, immediate). Schedule #3 against a real
latency/cost trigger, not speculatively.
