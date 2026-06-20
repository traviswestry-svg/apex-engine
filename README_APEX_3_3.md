# APEX 3.3 — Parallel Scanner + Live Dashboard

Fixes the "stuck on first scan pending" issue from 3.2.2 and replaces the static
dashboard with a live, interactive one.

## Root cause of the stuck dashboard

3.2.2 added three new sequential QuantData calls per ticker (order-flow,
dark-flow, dark-pool-levels), on top of an existing news fallback chain. All
default to enabled. With ~47 tickers and no concurrency, one scan cycle could
take many minutes — and if any of those endpoints were unreachable on your
QuantData plan, every single ticker paid a full 15–20s timeout for each dead
call. The dashboard only updates after a full cycle completes, so a slow scan
and a hung scan looked identical: "Background scanner started; first scan
pending..." forever.

## What changed

1. **Parallel ticker scanning.** `run_scan_once()` now fans tickers out across
   a thread pool (`SCAN_WORKERS`, default 8) instead of scanning one at a time.
2. **Circuit breaker per data source.** A new `CircuitBreaker` tracks
   consecutive failures per endpoint (QuantData net-flow, order-flow,
   dark-flow, dark-pool-levels, Massive/Benzinga news, Polygon news fallback,
   direct Benzinga). After `BREAKER_MAX_FAILURES` (default 3) failures in a
   single scan cycle, further calls to that endpoint are skipped instantly —
   returning a neutral score immediately — instead of burning a timeout per
   remaining ticker. It resets at the start of every new cycle, so a transient
   outage gets retried next time.
3. **Live scan progress.** `STATE` now tracks `scan_in_progress`,
   `scan_started_at`, and `last_scan_duration_seconds`, and the status message
   updates every 10 tickers (`"Scan running... 30/47 tickers analyzed"`)
   instead of staying frozen until the whole cycle finishes.
4. **Thread-safety fixes that come with concurrency:** `SENT_ALERTS` is now
   guarded by a lock (claimed before sending, released back if Telegram send
   fails, so a transient Telegram error doesn't permanently suppress a real
   alert) — needed because multiple ticker threads can now reach `maybe_alert`
   at the same time.
5. **New interactive dashboard.** `/` now polls `/dashboard.json` every 12s
   client-side instead of doing a full-page reload every 60s. It surfaces the
   thing that was previously invisible — system health — front and center:
   a live scan indicator, per-source status chips, and a circuit-breaker strip
   that shows exactly which data source is down and how many calls it's
   skipped this cycle. Plus ticker search, status filters, sortable scores,
   and collapsible "why this setup" detail per card.
6. **`/api/diagnostics` and `/health`** now also report `scan_in_progress`,
   `scan_started_at`, `last_scan_duration_seconds`, and the circuit breaker
   snapshot, so you can check from the API whether a scan is genuinely running
   or stuck without needing the dashboard open.

## New environment variables

```text
SCAN_WORKERS=8            # concurrent ticker analysis threads
BREAKER_MAX_FAILURES=3    # consecutive failures before an endpoint is skipped for the rest of the cycle
```

## Recommended next deploy step

After this deploys, watch `/api/diagnostics` for a minute. If
`circuit_breaker.open_circuits` lists `quantdata_dark_flow`,
`quantdata_order_flow`, or `quantdata_dark_pool_levels` on every cycle, those
endpoints are likely wrong paths or unavailable on your current QuantData
plan — worth confirming the exact route names with QuantData support rather
than leaving them silently neutral forever.

## Retiring the old static dashboard

The separate `apex-dashboard-main` repo (`index.html` + a hardcoded
`dashboard.json`) is from the old 2.3 engine schema and is not wired to this
service at all. Recommend deleting that repo — it can only cause confusion
about which dashboard is "real."
