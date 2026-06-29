# APEX 6.4.1 Changelog — Consolidation Sprint

**Version:** 6.4.1_APEX_TERMINAL_CONSOLIDATION  
**Date:** 2026-06-28  
**Baseline:** 6.4.0_APEX_TERMINAL_1_0

## Summary

Consolidation sprint focused on three things: one canonical data object,
story prose that reasons rather than describes, and a trade coach that
produces a complete actionable plan.

---

## engine/market_state.py (NEW — 311 lines)

**Canonical Market State Object.**

Single source of truth assembled once per request from already-fetched data.
No engine fetches data independently. Passed to story, coach, and replay.

### Fields produced:
- **Price / session**: ticker, price, session_state, is_tradeable, minutes_open
- **Structure**: vwap, poc, vah, val, hvn, lvn, poc_migration, poc_delta,
  auction_state, profile_available, poc_vwap_confluent, confluence_level
- **Location flags**: price_vs_poc (ABOVE/BELOW/AT), price_vs_va (ABOVE_VAH/BELOW_VAL/INSIDE)
- **Nearest levels**: nearest_support, nearest_support_label, nearest_resistance, nearest_resistance_label
- **Gamma**: call_wall, put_wall, zero_gamma, gex_score, gamma_regime (POSITIVE/NEGATIVE/MIXED),
  flip_risk, flip_proximity
- **Flow**: flow_bias, net_premium, call_premium, put_premium, sweep_count, flow_momentum, divergence_type
- **Tape**: tape_bias, tape_net, tape_sweeps, tape_blocks
- **Execution**: pine_state (CONFIRMED/WAITING/REJECTED), signal_fresh, signal_secs,
  signal_matches, ici, decision_state, approved_side
- **Risk levels**: entry_zone, stop, target1, target2, contract_hint

### Added to /api/institutional_os response:
- `result["market_state"]` — the full canonical object

---

## engine/story.py (REWRITTEN — 713 lines) — Story Engine 3.1

**From metrics-in-prose to reasoning prose.**

### Chapter architecture:

Each chapter now answers: *what is happening and what does it mean for the trade?*

| Chapter | Old | New |
|---------|-----|-----|
| Regime | "Gamma regime is Negative Gamma: high volatility. VIX at 18.2." | "Dealers are in negative gamma — they amplify moves in both directions. Momentum trades work better than mean-reversion today." |
| Auction | "POC 7349. VAH 7358. Val 7341. Migration: RISING." | "Buyers have defended VAL and reclaimed POC. POC has migrated higher over the session — buyers are accepting these prices as fair value." |
| Flow | "Institutions are accumulating on SPX (+$2.4M net). 7 sweeps — urgency high." | "Aggressive institutional buying — $2.4M net with 7 sweeps. Institutions are paying the ask." |
| Tape | "Flow tape: 7 orders — 5 sweeps, 2 blocks. Net +$1.8M. Bias: BULLISH." | "The sweep tape is showing 5 call sweeps with $1.8M net buy premium — institutions are paying the ask. This confirms the bullish flow read." |
| Pine | "Pine state: WAITING FOR PINE." | "Pine confirmation is missing. APEX is in WATCH_CALLS — all conditions are aligned except for the execution trigger. Wait for a fresh Pine signal before entering." |
| Verdict | "WATCH CALLS. 4 of 6 engines favor calls." | "APEX is in WATCH CALLS — conditions favor calls but not all gates are clear. Price is above POC (7349). Waiting for Pine confirmation to enter." |

### Executive summary — the key output:

The summary now synthesizes auction, tape, gamma, and decision state into
one tradeable paragraph instead of a list of conditions.

**Example ENTER_CALL:**
> "Price is above POC (7349.25) with POC migrating higher — buyers are accepting these prices. POC and VWAP confluent near 7347. 5 call sweeps on tape. Pine confirmed (3m 12s remaining). APEX is signaling ENTER CALL — SPX 7350C 0DTE. Entry: 7348–7352. Stop: $7343.50. T1: $7362, T2: $7375. ICI: 84."

**Example WATCH_CALLS:**
> "Buyers are accepting prices above VAH (7358) with POC migrating higher. QuantData tape shows 4 call sweeps confirming bullish bias. APEX is in WATCH CALLS — waiting for Pine confirmation before entering calls."

**Example NO_TRADE:**
> "No institutional consensus — 3 engines bullish, 3 bearish, 0 neutral. Sit out until the market shows a clear direction."

### Session awareness:
- [PRE-MARKET] / [AFTER-HOURS] / [CLOSED] prefix on all summaries
- Auction chapter says "waiting for session bars" before profile is available

### Canonical input path:
- Accepts `market_state` (canonical dict) — preferred in 6.4.1
- Legacy individual-arg path preserved for backward compat

---

## engine/trade_coach.py (REWRITTEN — 560 lines) — Trade Coach 3.1

**From a metrics display to a complete decision plan.**

### New outputs:

**Entry guidance** — plain language, context-aware:
- Explains *where* to enter and *why* (e.g. "Wait for pullback into POC/VWAP confluence near 7347 — that is your optimal entry")
- Different guidance for above VAH, inside value, POC pullback, PUT entries

**Stop narrative + Invalidation level** (separate concepts):
- Stop: the price at which you exit to protect capital
- Invalidation: the structural level that ends the thesis entirely
  (e.g. "Close below POC/VWAP confluence — a close below 7344 ends the bullish thesis")

**Target guidance** — context-labeled:
- T1 identified as VAH when near it: "T1: $7362 (VAH — scale 50% here)"
- T2 identified as Call Wall when near it: "T2: $7375 (Call Wall — trail remainder)"

**Scale-out plan** — step by step:
1. "At T1 ($7362): exit 50% of the position"
2. "Move stop to entry (breakeven)"
3. "Above T1: trail stop 5 points below price"
4. "At T2 ($7375): exit remaining 50% unless momentum is accelerating"
5. Wall level added as additional target if applicable

**Do-not-trade conditions** — specific and structural:
- "Price drops below VWAP (7347.50) before your fill"
- "Price closes below POC (7349.25) on a 5-minute bar"
- "Pine signal expires in Xm — enter promptly or wait for next trigger"
- "Flow tape shows 4 active put sweeps against your direction"
- "Zero-gamma flip is only 2.5 points away — regime can shift fast"

**Confirmation checklist** — 7–9 items with met/unmet status:
- Session is live / tradeable
- ICI ≥ 65
- Pine signal confirmed and fresh
- Flow bias aligns with trade
- Tape bias aligns or neutral
- Price on correct side of POC
- POC not migrating against trade
- No flip-risk / gamma instability

**Readiness score** — 0–100, % of checklist items met

### Main action narrative examples:

ENTER CALL:
> "ENTER CALL. SPX 7350C 0DTE (3m 12s). Entry: 7348–7352. Stop: $7343.50 — invalidation: close below POC/VWAP confluence; a close below $7344 ends the bullish thesis. T1: $7362 (VAH — scale 50% here). T2: $7375 (Call Wall — trail remainder)."

WATCH:
> "Watch calls — conditions are building but not ready. Primary blocker: Pine signal not confirmed. Wait for pullback into POC/VWAP confluence near 7347 — that is your optimal entry."

NO TRADE:
> "No trade. Blocked by: ICI at 48 (minimum 50 required); Pine signal not confirmed. Wait for all gates to align before entering."

---

## app.py — 6.4.1 Changes

### Canonical Market State wiring:
- `build_canonical_market_state()` called after nine-engine pipeline
- Receives: flow_snapshot, volume_bundle, result, tape_summary, session_ctx
- Result stored as `result["market_state"]`
- Passed into Story 3.1 and Trade Coach 3.1 as `market_state=canonical_ms`

### Enriched replay frame:
Added to every captured frame (in addition to existing fields):
- `executive_summary` — the Story 3.1 summary at that moment
- `coach_action` — the Trade Coach 3.1 action narrative at that moment
- `coach_entry`, `coach_stop`, `coach_t1`, `coach_t2`
- `price_vs_poc`, `price_vs_va`, `poc_migration`, `poc_vwap_confluent`
- `flow_bias`, `pine_state`, `signal_secs`, `gamma_regime`, `flip_risk`

### Import guard:
- `build_canonical_market_state` imported with fallback (non-fatal)

---

## Frontend Changes

### static/js/apex_os.js — renderCoachSnapshot (UPGRADED)

Full Trade Coach 3.1 decision center render:
- Main action block (color = decision state: green/amber/red)
- 2×4 levels grid: contract, entry, stop, invalidation, T1, T2, POC, VWAP
- Readiness bar (0–100% animated)
- Scale-out plan (step list)
- Do-not-trade conditions
- Checklist (✓/✗ per item with notes)

### static/js/apex_os.js — loadReplayFrame (UPGRADED)

Enriched replay frame display:
- Story snapshot: the executive_summary at that moment (italicized, blue border)
- Decision badge inline in header
- Coach action + entry/stop/targets from that frame
- 2-column meta grid: ICI, price, POC, vs POC/VA, migration, auction, gamma, flow/tape, pine, grade

### static/css/apex_os.css — New styles

Trade Coach 3.1:
- `.coach-action-block` — color-coded action paragraph
- `.coach-levels-grid` — 2×4 levels grid
- `.coach-readiness` — animated readiness bar
- `.coach-scale-plan` — step-list for scale-out
- `.coach-dont-trade` — red-tinted do-not-trade list
- `.coach-checklist` — ✓/✗ checklist items

Replay:
- `.rf-header` — header row with decision badge
- `.replay-story` — story snapshot with blue left border
- `.replay-coach-action` — coach narrative in green tint
- `.replay-meta-grid` — 2-column frame metadata

---

## Compile Check
```
python -m py_compile app.py apex_engines.py engine/*.py
# Result: ALL CLEAR
```

## Changed Files

| File | Change |
|------|--------|
| `engine/market_state.py` | NEW — 311 lines |
| `engine/story.py` | REWRITTEN — 713 lines (Story Engine 3.1) |
| `engine/trade_coach.py` | REWRITTEN — 560 lines (Trade Coach 3.1) |
| `engine/__init__.py` | Added build_canonical_market_state export |
| `app.py` | VERSION bump; canonical state wiring; enriched replay frames |
| `static/js/apex_os.js` | renderCoachSnapshot full rebuild; loadReplayFrame enrichment |
| `static/css/apex_os.css` | Coach 3.1 and replay styles |

## Unchanged
Everything else. apex_engines.py untouched.
