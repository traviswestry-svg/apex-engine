# APEX 8.0 — Mission Control (Increment 1)

Default operator workspace that answers, in one scannable view:
**What are institutions doing? · Should I trade? · Is now the moment? · What's the expected path?**

This is the first v8 increment: the composite backend endpoint plus the Mission Control
frontend panel. It is **additive and non-breaking** — no engine, calculation, or existing
route was rewritten. Your current dashboard is retained verbatim as the **Institutional
Analysis** tab.

---

## ⚠️ Read this first — repo state correction

While building this I found that your **committed GitHub HEAD (`apex-engine`, commit
`Add files via upload`) does NOT contain the `/api/mission_control` backend.** HEAD has 55
routes ending at `/chart`; there is no `mission_control`, `_build_expected_path`, or shared
`_compute_engine_health` in it.

The `app.py` in this package is your HEAD **plus** a complete, self-contained
`/api/mission_control` backend (243 added lines). I validated it end-to-end (compiles clean;
cold and warm responses return correct payloads via the Flask test client). It is **pure
composition** — it reads `STATE["last_result"]` populated by `/api/institutional_os`, makes
no new external API calls, and introduces no new math.

Because Mission Control's frontend calls `/api/mission_control`, **you must ship the backend
too.** If you drop only the three frontend files onto your current HEAD, the panel will sit
on its "waiting for first scan" state forever because the endpoint 404s.

Two ways to take the backend, your choice:
- **Simplest:** use `backend/app.py` as-is (it's HEAD + the endpoint).
- **Review-first:** apply `backend/app_backend_mission_control.patch` to your own `app.py`
  (`git apply app_backend_mission_control.patch`) so you can read exactly the 243 lines
  being added before merging.

---

## What's in the box

```
apex8_mission_control/
├── frontend/
│   ├── apex_os.html   → templates/apex_os.html   (tab bar + Mission Control pane)
│   ├── apex_os.css    → static/css/apex_os.css   (+195 lines, scoped .mc-*)
│   └── apex_os.js     → static/js/apex_os.js      (+~270 lines, self-contained module)
└── backend/
    ├── app.py                              → app.py (HEAD + endpoint)
    └── app_backend_mission_control.patch   → isolated backend diff vs your HEAD
```

## Backend — `/api/mission_control`

Three additions (all in `app.py`):

1. **`_compute_engine_health(last)`** — extracted the health computation out of
   `/api/engine_health` into a shared helper so both routes use one source of truth
   (returns `(rows, counts)`). `/api/engine_health` behaves identically to before.
2. **`_build_expected_path(last)`** — composes the level map (strike magnets → dealer
   walls → value area) around the live price, deduped within 2 pts, split above/below,
   plus the pin block. Zero new math.
3. **`GET /api/mission_control?ticker=SPX`** — one payload composing the canonical
   Institutional Intelligence object, Execution Intelligence, consensus, ICI, risk,
   flow/dealer/auction summaries, `exec_score_history` (for the sparkline), and engine
   health. Returns `{ok:false, available:false, reason:…}` gracefully until the first
   `/api/institutional_os` scan populates `STATE["last_result"]`.

The endpoint never triggers a scan and never blocks on external APIs, so it's cheap to
poll on a tight interval.

## Frontend — Mission Control tab

- New **Mission Control** tab, set as the **default** workspace. **Dashboard** is retained
  and relabeled **Institutional Analysis** (unchanged internals).
- Fully **self-contained module** (`loadMissionControl` / `renderMissionControl`) with its
  **own 5-second poll** of `/api/mission_control`, decoupled from the heavy
  `/api/institutional_os` loop — a failure on either side never affects the other. Follows
  your non-fatal-module preference: every render guard is try-safe and degrades to a
  warming-up state.
- All CSS is scoped under `.mc-*` and all DOM ids under `mc*`, derived entirely from your
  existing `:root` tokens — it cannot collide with or restyle any existing panel.

### Layout (top → bottom)
1. **Hero decision band** — execution-score gauge (the signature element, color-shifts
   blue→amber→green), institutional bias badge, `WATCH → PREPARE → ARMED → EXECUTE` stage
   ladder, timing line, one-line narrative, engine-agreement bar, institutional confidence
   with a score-history sparkline.
2. **Intelligence strip** — Flow · Dealer · Auction, color-coded by direction.
3. **Professional Trade Card** — activates at ARMED/EXECUTE: direction, entry/stop/
   targets, R:R, contract hint, invalidation.
4. **Expected Path** — ranked levels above/below the live price with the pin block.
5. **Engine Consensus** + **Why** — vote table (skipped engines dimmed) and the evidence
   chain with the primary-risk callout.
6. **Engine health footer** — counts, per-engine status dots, freshness/stale/partial.

## Deploy

Copy the four files to their paths and restart the Render web service:

```
frontend/apex_os.html  → templates/apex_os.html
frontend/apex_os.css   → static/css/apex_os.css
frontend/apex_os.js    → static/js/apex_os.js
backend/app.py         → app.py          # or apply the .patch to your own app.py
```

No new env vars, no new dependencies, no schema changes. Bump `asset_version` (or your
cache-buster) so the CSS/JS refresh.

## Verify after deploy
1. `GET /api/mission_control?ticker=SPX` returns `{ok:false, available:false}` before the
   first scan, then a full payload after `/api/institutional_os` runs once.
2. `/apex_os` opens on **Mission Control** by default; **Institutional Analysis** still
   renders your existing dashboard.
3. Switching ticker (SPX/SPY/QQQ/IWM) refreshes Mission Control.

## Validation performed here
- `app.py` compiles; `apex_os.js` passes `node --check`.
- Flask test client: cold path (correct graceful empty) and warm path (seeded ARMED
  setup) both return correct composed payloads.
- Every JS-referenced DOM id exists in the template.
- Rendered headless (Chromium) and visually reviewed with a seeded ARMED payload.

## Not in this increment (per the incremental plan)
Weekend Mode, Historical Learning ("similar setup → win rate/MFE/MAE"), the app.py
split into api/services/orchestration, and typed Pydantic boundaries. These come after
the core workspace is stable in front of you.
