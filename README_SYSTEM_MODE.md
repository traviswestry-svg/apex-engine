# APEX — Trustworthy first paint: System Mode + version consistency

Fixes the "is it waiting or broken?" problem. The header now tells you the truth
in the first second — before any JavaScript loads — and every status endpoint
reports the same version.

## Deploy (3 files, overwrite in place)
```
app.py                    → app.py
templates/apex_os.html    → templates/apex_os.html
static/js/apex_os.js      → static/js/apex_os.js
```

## What changed

### 1. Market-holiday awareness (the root of the July 3 confusion)
`session_status()` had no holiday calendar, so a full-day closure (e.g. July 3,
Independence Day observed) read as `AFTER_HOURS` with "ES open." Added
`US_MARKET_HOLIDAYS` (2026–2027) and `is_market_holiday()`; `session_status()`
now returns `CLOSED` on holidays. This corrects the state everywhere at once.
*(Update the holiday set annually.)*

### 2. One canonical System Mode
New `system_mode()` collapses the internal session states into four operator
labels, each with a plain-English message and a "live flow expected?" flag:

| Mode        | When                                   | Pill color | Flow |
|-------------|----------------------------------------|-----------|------|
| `LIVE`      | RTH open (9:30–16:00 ET, trading day)  | green     | yes  |
| `PRE-RTH`   | Pre-market on a trading day            | amber     | no   |
| `OVERNIGHT` | Post-close / futures session           | amber     | no   |
| `CLOSED`    | Weekend or market holiday              | gray      | no   |

The three colors are deliberate: **green = live, amber = waiting, gray = closed.**
That's the "waiting vs broken" signal at a glance.

### 3. Meaningful first paint (before JS)
`/apex_os` now passes the mode to the template, which **server-renders** the
header pill and the status banner. With JavaScript disabled the header already
reads, e.g.:

> **CLOSED — MARKET HOLIDAY** · Market closed for the holiday. No live SPX
> options flow. Showing last profile and next-session game plan. · Next RTH: Mon 9:30 AM ET

The client still replaces the banner with the full per-component breakdown on the
first poll, but the trustworthy state is there from byte one. The old
`LOADING` pill and `display:none` banner are gone. The Mission Control body still
shows "Waiting for first scan cycle…" — that panel genuinely needs data, and the
header now makes clear whether that's expected (closed/overnight) or not (LIVE).

### 4. Consistent version + system_mode across endpoints
`/health`, `/api/status`, and `/api/market_status` now all report the same
`version` (previously `/health` exposed it only as `mode`, a legacy alias that's
kept) plus a `system_mode` field. `/apex_os` renders the same `VERSION`.
Verified equal in testing.

`GET /health` now returns:
```json
{ "ok": true, "version": "7.0.1_APEX_EIGHT_FOUNDATION",
  "mode": "7.0.1_APEX_EIGHT_FOUNDATION",   // legacy alias
  "system_mode": "CLOSED",
  "system_mode_detail": { "mode": "CLOSED", "title": "...", "message": "...",
                          "next_rth": "Mon 9:30 AM ET", "flow_live": false,
                          "is_holiday": true, ... },
  "session": "CLOSED", ... }
```

## JS
`renderSession()` now maps the session state to the same four labels/colors, so
after the first poll the pill stays consistent with the server render instead of
reverting to a bare state name. It prefers `system_mode` from the payload when
present.

## Verified
- `app.py` compiles; `apex_os.js` passes `node --check`.
- `is_market_holiday('2026-07-03') = True`, `'2026-07-06' = False`.
- All four modes map with correct labels/colors.
- `/health`, `/api/status`, `/api/market_status` report identical `version` and a
  consistent `system_mode`.
- `/apex_os` raw HTML (JS stripped) contains the `CLOSED` pill and the full
  holiday banner — confirmed by rendering with scripts removed.

## Note
`system_mode` reflects full-day closures and RTH hours. It does not yet special-case
the two early-close days (day after Thanksgiving, Christmas Eve) — those still read
`LIVE` during their shortened session, which is correct for "is flow live?" but
won't show a "half day" label. Easy to add later if you want it.
