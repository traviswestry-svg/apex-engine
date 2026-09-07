# APEX_6_0_3_6_0_4_CHANGELOG.md

## APEX Institutional OS — v6.0.3 + v6.0.4

**Sprint 6.0.3** — Institutional Ribbon, Confidence Index, Trade Coach, Engine Matrix  
**Sprint 6.0.4** — Flow Intelligence 2.0, Story Engine, Session Replay, Session Review  
**Date:** 2025-06  
**Type:** Frontend — no backend changes

---

## Sprint 6.0.3 — Dashboard Rebuild

### What changed

The old `/apex_os` dashboard was a single monolithic HTML file with limited structure, hardcoded rendering, and no modular layout. Sprint 6.0.3 completely rebuilds it using two new static files (`apex_os.css` + `apex_os.js`) and replaces `APEX_OS_HTML` in `app.py`.

All data continues to come from `/api/institutional_os` — no backend changes.

### Institutional Ribbon (full-width, always visible)

8-cell full-width ribbon across the top of the dashboard, always visible regardless of active tab.

| Cell | Source field |
|---|---|
| SPX Price | `ribbon.spx_price` |
| Inst. Confidence | `ici.ici` + `ici.ici_label` + `grade` |
| Decision | `decision_state` + `readiness` |
| Net Flow | `ribbon.net_flow` + `ribbon.flow_momentum` |
| Call Wall | `ribbon.call_wall` / `gamma_regime.call_wall` |
| Zero Gamma | `ribbon.zero_gamma` / `gamma_regime.zero_gamma` |
| VWAP | `ribbon.vwap` / `structure.vwap` |
| Updated | `ribbon.updated_at_et` |

Color coding: green ≥ 70 ICI, amber 50–69, red < 50.

### Institutional Confidence Index Panel

- Large numerical display (0–100) color-coded by `ici.ici_color`
- Four component bars with weights: Conviction (50%), Signal Freshness (20%), Gamma Stability (15%), Flow Momentum (15%)
- Each component shows fill bar + value
- Grade letter (A+ / A / B+ / B / C / D) from `grade`
- ICI status sentence from `ici.ici_status`

### Decision + Signal Decay

- Decision badge (`ENTER_CALL`, `ENTER_PUT`, `READY`, `WATCH_CALLS`, `WATCH_PUTS`, `NO_TRADE`, `PREPARING`)
- Executive summary text
- Consensus action line
- Signal decay progress bar with real-time countdown (`execution.signal_seconds_remaining`)
- Gate checklist (4 gates): ICI ≥ 70, consensus directional, Pine confirmation, no A+ divergence block

### Trade Coach Panel

Reads from `trade_coach` + `risk`:

- Action sentence (what to do now)
- Trade plan grid: Contract, Entry Zone, Stop, Target 1, Target 2, Gamma Management
- Blockers list (amber warnings for things preventing entry)
- Next confirmation required
- Gamma management rule from `gamma_regime.trade_rules`

### Engine Matrix

- Visual bar chart for all 6 contributing engines
- Each row: Engine name → Vote badge (BULL/BEAR/NEUTRAL) → Score bar → Score value
- Click any row to expand engine notes (up to 3 notes)
- Consensus bar at top: proportional bull/bear/neutral segments from `consensus.n_bullish` / `n_bearish` / `n_neutral`

### Heatmap

Unchanged rendering logic — 4-column grid from `/api/heatmap`.

### Ticker selector

SPX / SPY / QQQ / IWM buttons at top. Switching ticker triggers a fresh `loadOS()` call.

---

## Sprint 6.0.4 — Flow Intelligence 2.0, Story, Replay, Review

All four features are new tabs on the `/apex_os` dashboard. Data reads from the same `/api/institutional_os` endpoint — `flow_intelligence`, `story`, `story_timeline` sub-objects.

### Flow Intelligence 2.0

Fully exposes the `flow_intelligence` engine output (previously only partially visible):

- Intelligence Score large display with inline progress bar
- **Divergence Alert block**: A+ Bearish, A+ Bullish, B divergence — each has distinct styling, description, remaining-time countdown bar, downgrade indicator
- **Absorption Confirmed block**: shows absorption description when `absorption === true`
- 6-metric grid: Flow Score, Order Flow, Net Premium, Call Premium, Put Premium, Sweep Count
- Momentum table: Bias, Flow Momentum, Flow Delta, Prev Score, Block Conviction, At Gamma Level, Session High/Low, Rolling High/Low, Gate Override
- Engine notes list (up to 8)

### Story Engine

- **Executive Summary card** — `executive_summary` in large highlighted block
- **Chapter Timeline** — all chapters from `story.chapters` in a vertical timeline with colored dots, chapter title, narrative text, and time
  - Significance-sorted (builds toward verdict)
  - Each chapter dot color matches its `color` field from the engine output
- **Full Institutional Narrative** — `story.full_narrative` in a formatted block

### Session Replay

- Data captured every 12 seconds (on each `loadOS()` cycle) into an in-memory array (up to 120 snapshots ≈ 24 minutes)
- Scrub bar to navigate any snapshot
- Prev / Next / Live buttons
- Selected frame shows: Decision state, ICI, Price, Exec state, executive summary, engine notes
- Event log showing last 30 snapshots in reverse chronological order

### Session Review

- Automatically logs ENTER_CALL, ENTER_PUT, and READY signals
- Each card shows: Ticker, Decision state, Time, ICI, Contract hint, Coach action, Executive summary
- Up to 40 entries retained per session (in-memory)
- Purpose: end-of-day review of all actionable signals that fired

---

## New Files

| File | Sprint | Purpose |
|---|---|---|
| `static/css/apex_os.css` | 6.0.3/6.0.4 | All OS dashboard CSS (ribbon, ICI, coach, matrix, flow2, story, replay, review) |
| `static/js/apex_os.js` | 6.0.3/6.0.4 | All OS dashboard JS — renders all panels from `/api/institutional_os` |
| `APEX_6_0_3_6_0_4_CHANGELOG.md` | — | This file |

## Modified Files

| File | Change |
|---|---|
| `app.py` | `APEX_OS_HTML` replaced with tabbed 5-panel dashboard loading static JS/CSS |

---

## Data Contract — What Each Panel Reads

All data from `GET /api/institutional_os?ticker=SPX&heatmap=1`

```
ribbon              → Institutional Ribbon cells
ici                 → ICI panel + decision confidence
  .ici              → score 0-100
  .ici_color        → GREEN / AMBER / RED
  .ici_label        → HIGH / MODERATE / LOW
  .ici_status       → one-sentence description
  .components       → {conviction, freshness, gamma_stability, flow_momentum}
decision_state      → Decision badge
grade               → Letter grade
readiness           → Readiness string
executive_summary   → Decision message
execution           → Signal decay bar
  .signal_seconds_remaining
  .signal_fresh
  .signal_matches_flow
consensus           → Engine matrix consensus bar
  .n_bullish / n_bearish / n_neutral
  .consensus_label
  .action
trade_coach         → Trade Coach panel
  .action
  .contract_hint / entry_zone / stop / target1 / target2
  .gamma_management
  .blockers
  .next_confirmation
engine_contributions → Engine Matrix rows
  [].label / engine / vote / score / notes
flow_intelligence   → Flow Intelligence 2.0 tab
  .intelligence_score / flow_score / order_flow_score
  .net_premium / call_premium / put_premium
  .sweep_count / sweep_aggression / block_conviction
  .divergence_type / divergence_direction / divergence_description
  .divergence_seconds_remaining / divergence_downgraded
  .absorption / absorption_description
  .flow_momentum / flow_flip / flow_delta
  .session_high / session_low / rolling_high / rolling_low
  .gate_override / notes
story               → Story Engine tab
  .chapters[]       → timeline entries with .time .chapter .text .color .significance
  .full_narrative   → prose paragraph
  .executive_summary
heatmap             → Heatmap card
```

---

## Endpoints to Verify

```
GET /apex_os                            → New tabbed dashboard (should load 5 tabs)
GET /api/institutional_os?ticker=SPX&heatmap=1  → Full JSON contract
GET /static/css/apex_os.css            → 200
GET /static/js/apex_os.js             → 200
GET /api/nine_engines?ticker=SPX       → Raw engine pipeline (unchanged)
GET /api/story?ticker=SPX              → Story endpoint (unchanged)
GET /api/v45/status                    → Health (unchanged)
```

## Compile Check

```bash
python -m py_compile app.py apex_engines.py engine/*.py
```

---

## Deployment — Render

1. Push to GitHub:
   - `app.py`
   - `static/css/apex_os.css`
   - `static/js/apex_os.js`
   - `APEX_6_0_3_6_0_4_CHANGELOG.md`

2. Render auto-deploys on push. No env var changes. No Node build.

3. All JS/CSS served as Flask static files from `./static`.

---

## Known Limitations

- **Replay is session-only** — snapshots are held in JS memory and lost on page reload. A future sprint can persist replay to the backend via a lightweight endpoint (POST `/api/replay_snap`).
- **Review is session-only** — same limitation. Future: persist to `apex_tracking.db`.
- **Ticker selector on OS page** — buttons for SPY/QQQ/IWM trigger a full pipeline re-run on the backend (same cost as loading the page for SPX). This is expected — same as the existing `?ticker=` query param behavior.
- **Tab state not persisted** — refreshing the page always returns to the Dashboard tab.
- **Story chapters** — sorted by `significance` in the backend engine. The frontend renders them in the order received. If `chapters` is empty but `story_timeline` is populated, the frontend falls back to `story_timeline`.
- **ICI components** — weights shown are from `ici.weights` returned by the engine (50/20/15/15). If the backend changes weights, the display updates automatically.
