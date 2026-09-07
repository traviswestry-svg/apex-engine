# APEX 9.0 — Phase 0: Repository Audit

**Scope:** the audit the APEX 9.0 master prompt requires before any production code
changes (*"Begin with Phase 0… before changing production code"*, §32). No
production code was modified in this pass.

**Headline finding:** APEX 9.0 is largely **already built**. Measured against the
spec's own section list, roughly **two-thirds of the target system exists and
runs today**. The spec's framing — *"transform APEX from a collection of
dashboards and indicators into a unified Institutional Decision Engine"* —
understates the current codebase, which already has a canonical bus, nine
engines, confluence scoring, structured decisions, a risk guard, a trade coach,
an active-trade director, outcome grading, and replay.

This matters because `ARCHITECTURE.md` already warns that the 7.5 / 8.0 / 8.5
specs proposed building things that existed. **APEX 9.0 repeats that pattern.**
The value here is not a rewrite; it is closing four real gaps and deleting one
dead module pair.

---

## 1. Architecture map

    TradingView ──POST /tv_signal──┐
                                   ▼
    Polygon ─┐              ┌──────────────────┐
    QuantData ├─providers──▶│  scanner_loop    │ (background thread, 300s)
    Massive  ─┤             │  + headless      │
    Benzinga ─┘             │  IOS compose 7.6 │
                            └────────┬─────────┘
                                     ▼
                     ┌───────────────────────────────┐
                     │  /api/institutional_os        │  ← THE COMPOSER
                     │  builds STATE["last_result"]  │
                     └───────────────┬───────────────┘
                                     │  (canonical Data Bus)
      ┌──────────────┬───────────────┼───────────────┬──────────────┐
      ▼              ▼               ▼               ▼              ▼
    confluence   decision_intel  range_intel   premium_strategy  event_calendar
      │              │               │               │              │
      └──────────────┴───────────────┴───────┬───────┴──────────────┘
                                             ▼
                            read-only consumers → /apex_os dashboard
                                             │
                            director/ (position lifecycle) ─▶ execution/ ─▶ E*TRADE

**Governing rule (already enforced):** `/api/institutional_os` composes the bus;
every feature engine is a **read-only consumer that recomputes nothing**. This is
precisely the spec's §2.2 "one canonical market-state model". It exists.

**Scale:** ~29,000 lines Python · `app.py` 7,681 · `apex_engines.py` 2,872 ·
~50 engine modules · 92 routes · 9 SQLite tables · 212 tests.

---

## 2. Existing-module inventory (selected)

| Domain | Module(s) | Spec section |
|---|---|---|
| Canonical bus | `app.py::api_institutional_os`, `engine/market_state.py`, `engine/data_bus.py` | §2.2 |
| Nine engines | `apex_engines.py::build_institutional_decision` | §3 |
| Flow | `engine/flow_intelligence.py`, `engine/flow_tape.py` | §4 |
| Dealer / GEX | `engine/dealer_positioning.py`, `engine/gamma.py` | §12 |
| Auction | `engine/auction_intelligence.py`, `engine/auction.py` | §5 (pipeline) |
| Volume profile | `engine/volume_profile.py` | §14 |
| Volatility | `engine/volatility.py`, `engine/range_intelligence.py` | §6 (pipeline) |
| Confluence | `engine/confluence.py` | §18 |
| Decision | `engine/decision_intelligence.py` | §18 |
| Trade construction | `engine/premium_strategy.py` (7.6) | §19 |
| Risk guard | `engine/execution/trade_risk_guard.py` | §20 |
| Trade coach | `engine/trade_coach.py` | §21 |
| Active trade director | `engine/director/*` (12 modules, own state machine) | §21 |
| Story | `engine/story.py` | §15 |
| Replay | `app.py::_record_replay_frame`, `replay_snapshots` | §16 |
| Outcome grading | `signal_evaluator.py` (MFE/MAE), `engine/director/evaluator.py` | §5, §17 |
| Mission control | `/api/mission_control` | §22 |
| Diagnostics | `engine/diagnostics.py`, `/api/engine_health` | §26 |
| Events | `engine/event_calendar.py` | §6 (pipeline) |
| Execution | `engine/execution/*`, `engine/brokers/etrade_adapter.py` | §28 |

---

## 3. Duplicate-module findings ⚠️ actionable

The repo's **own guard test already flags this** and has been failing:
`tests/test_architecture_canonical_imports.py::test_no_toplevel_engine_duplicate_of_subpackage_module`

| Orphan | Duplicates | Lines | Importers |
|---|---|---|---|
| `engine/contracts.py` | `engine/director/contracts.py` | 306 vs 296 | **0** (only `engine/persistence.py`) |
| `engine/persistence.py` | `engine/director/persistence.py` | 249 vs 234 | **0** |

Both expose **identical class names** (`Directive`, `DirectorContext`,
`HoldLevel`, `PositionView`, `ConflictReport`, `FlowAcceleration`,
`DirectivePersistence`, `_SymbolMemory`). They are an **orphaned fork** of the
director subpackage: two dead files that import only each other and are imported
by nothing. Every live consumer (`director.py`, `routes.py`, `lifecycle.py`,
`position.py`, `states.py`, `snapshots.py`, `conflict.py`, `thesis.py`,
`hold_level.py`) imports the `director/` versions.

**Recommendation:** delete `engine/contracts.py` and `engine/persistence.py`.
This resolves one of the two permanently-failing tests and removes a genuine
footgun — a future import of `engine.contracts` would silently bind a stale
fork of the director's core types. *Deferred pending your approval: deleting
files is destructive and outside a read-only audit.*

---

## 4. Data-provider map

| Provider | Env | Used for | Notes |
|---|---|---|---|
| Polygon | `POLYGON_API_KEY` | bars, chain, OI, VIX, futures | 15 call sites; primary |
| QuantData | `QUANTDATA_API_KEY`, `QUANTDATA_BASE_URL` | options flow, flow tape, news | `sync:false` on Render → **can be unset in prod** |
| Massive | `MASSIVE_API_KEY`, `MASSIVE_BASE_URL` | flat files | ingest path |
| Benzinga | `BENZINGA_API_KEY` | news/catalysts | |
| E*TRADE | `ETRADE_*` | execution (sandbox default) | `ETRADE_ENABLE_TRADING` gate |
| Telegram | — | alerts | `send_telegram` |

Feature flags present: `ORDER_FLOW_ENABLED`, `GEX_ENABLED`, `SPINE_ENABLED`,
`DARK_POOL_*`, `DYNAMIC_TICKERS_ENABLED`, `POSITION_MONITOR_ENABLED`,
`COMPOSE_IOS_IN_SCANNER` (7.6), `RUN_SCANNER_ON_IMPORT`. The spec's §2.1
"add feature flags for major new capabilities" is an established pattern here.

---

## 5. Schema map

| Table | Owner | Purpose |
|---|---|---|
| `apex_signals` | `app.py` | APEX decision spine + outcomes |
| `pine_signals` | `signal_evaluator.py` | Pine webhooks + MFE/MAE grading |
| `premium_recommendations` | `engine/premium_strategy_routes.py` | structure recs + settled outcomes (7.6) |
| `director_directives` | `engine/director/store.py` | director directives |
| `director_outcomes` | `engine/director/evaluator.py` | director grading |
| `range_projection_history` | `engine/range_intelligence.py` | range projections vs actuals |
| `replay_snapshots` | `app.py` | replay frames |
| `tracked_ideas` | `app.py` | multi-ticker scanner ideas |
| `trade_reviews` | `app.py` | manual trade reviews |

All under `DB_PATH` (`/data/apex_tracking.db` on Render, persistent disk).
**No migration framework exists** — tables are `CREATE TABLE IF NOT EXISTS` at
runtime, with ad-hoc `ALTER TABLE ADD COLUMN` migration (7.6 pattern). The spec's
§2.1 "add migrations for schema changes" would need this formalized.

---

## 6. UI-route map

| Route | Template | Notes |
|---|---|---|
| `/apex_os` | `apex_os.html` | main dashboard; 3 always-on bands + 9 tabs |
| `/apex_os/trade_command` | `trade_command.html` | execution page |
| `/chart`, `/flow`, `/assistant`, `/dashboard.json`, `/scanner` | legacy | older surfaces |

Existing tabs: `mission · exec · chart · flow2 · dashboard · story · tape ·
replay · review`.
Spec §7 wants: `Flow · P/L · Greeks · Heatmap · GEX · OI · Volume Profile ·
Story · Replay`.

Overlap: Flow (`flow2`/`tape`), Story, Replay. **Absent as tabs:** P/L, Greeks,
GEX, OI, Volume Profile — though `/api/volume_profile`, `/api/heatmap`,
`/api/diagnostics/gamma`, and OI (via `engine/options/options_data_bus.py`)
already supply the data. These are largely **presentation gaps, not engine gaps.**

---

## 7. Gap analysis — spec §§ vs reality

| § | Requirement | Status | Evidence |
|---|---|---|---|
| 2.2 | canonical market-state | ✅ **EXISTS** | `STATE["last_result"]`, read-only consumers |
| 2.2 | ES price + ES-SPX basis | 🟡 **PARTIAL** | only in `engine/overnight.py`; not on the bus |
| 2.3 | evidence before decisions | ✅ **EXISTS** | confluence evidence, decision_intelligence, premium `reason[]`/`story[]` |
| 2.4 | degraded states | 🟡 **PARTIAL** | has `LIVE/STALE/CLOSED/WARMING/UNAVAILABLE`; missing `DELAYED`, `PARTIAL`, `SIMULATED` |
| 3 | 14-stage pipeline | ✅ **EXISTS** (stages 1–13) | missing only stage 14 (learning/calibration) |
| 4.1 | flow inputs | ✅ **EXISTS** | `flow_intelligence.py`, `flow_tape.py` |
| 4.2 | **flow classification taxonomy** | ❌ **MISSING** | no sweep/block/roll/hedge/spread-leg classifier |
| 4.3 | **flow clustering** | ❌ **MISSING** | no cluster model |
| 4.4 | institutional conviction score | ✅ **EXISTS** | ICI score, component-exposed |
| 5 | **flow P/L tracking** | ❌ **MISSING** | only position-level `unrealized_pnl` in director |
| 6 | **Trade Cards + lifecycle** | 🟡 **PARTIAL** | `tracked_ideas`, `apex_signals`, director state machine exist — but no unified flow-cluster card with the §6.2 DETECTED→REVIEWED lifecycle |
| 7 | synchronized workspace | 🟡 **PARTIAL** | tabs exist; no shared cursor/zoom/selection state |
| 8–16 | per-tab views | 🟡 **PARTIAL** | Flow/Story/Replay exist; P/L, Greeks, GEX, OI, VP need surfacing |
| 17 | **historical similarity / feature store** | ❌ **MISSING** | no similarity engine, no feature store, no leakage guard |
| 18 | confluence + decision | ✅ **EXISTS** | `confluence.py`, `decision_intelligence.py` |
| 19 | trade construction | ✅ **EXISTS** | `premium_strategy.py` (7.6) — structure, strikes, POP, exits |
| 20 | risk guard | ✅ **EXISTS** | `trade_risk_guard.py` |
| 21 | trade coach + director | ✅ **EXISTS** | `trade_coach.py`, `engine/director/*` |
| 22 | mission control | ✅ **EXISTS** | `/api/mission_control` |
| 26 | observability | ✅ **EXISTS** | `diagnostics.py`, `/api/engine_health` |
| 27 | testing | ✅ **EXISTS** | 212 tests |
| 28 | execution safety | ✅ **EXISTS** | sandbox default, `ETRADE_ENABLE_TRADING` gate |

**Score: ~14 exist · ~6 partial · ~4 genuinely missing.**

### The four real gaps
1. **§4.2/4.3 — flow classification + clustering.** The engine reads flow but
   never classifies a print as sweep/block/roll/hedge/spread-leg, nor aggregates
   prints into clusters. This is the spec's true centre of gravity.
2. **§5 — flow P/L tracking.** No theoretical per-order/per-cluster P/L with
   MFE/MAE and conservative marks.
3. **§6 — unified Trade Cards.** Three partial precursors exist and none is the
   spec's card.
4. **§17 — historical pattern intelligence.** No feature store, similarity
   engine, or leakage prevention. **Highest effort, highest risk.**

---

## 8. Implementation plan (revised from the spec's phases)

The spec's Phase 1–6 assumes a greenfield build. Re-sequenced against what
exists:

| Phase | Work | Effort | Notes |
|---|---|---|---|
| **0a** | Delete `engine/contracts.py` + `engine/persistence.py` | XS | fixes failing guard test; needs approval |
| **0b** | Make `test_decision_intelligence` date-independent | XS | inject `events={}` fixture (see 7.6.1 changelog) |
| **1a** | Flow event normalization + **classification** (§4.2) | M | deterministic rules first, per spec |
| **1b** | Flow **clustering** (§4.3) | M | depends on 1a |
| **1c** | Add ES price + ES-SPX basis to the bus (§2.2) | S | `overnight.py` already computes basis |
| **1d** | Extend degraded-state vocabulary (§2.4) | S | add `DELAYED`/`PARTIAL`/`SIMULATED` |
| **2a** | **Trade Cards** + lifecycle (§6) | M | build on `apex_signals`, not a new silo |
| **2b** | **Flow P/L tracking** (§5) | M | reuse `signal_evaluator` MFE/MAE spine |
| **3** | Surface existing data as tabs: GEX, OI, VP, Greeks, P/L (§10–14) | M | data exists; presentation only |
| **4** | Workspace synchronization (§7) | M | shared selection state across tabs |
| **5** | **Historical similarity + feature store** (§17) | L | do last; highest risk |
| **6** | Calibration / learning reports (§3 stage 14, §5 of phases) | M | depends on 5 |

**Sequencing principle:** every phase must land as a read-only consumer of the
existing bus, exactly as `confluence` / `decision_intelligence` /
`premium_strategy` do. Nothing here justifies a new composer.

---

## 9. Risk register

| # | Risk | Sev | Mitigation |
|---|---|---|---|
| R1 | **Spec proposes rebuilding existing engines** — the failure mode `ARCHITECTURE.md` already documents for 7.5/8.0/8.5 | **High** | This audit. Build only the four real gaps; extend, never fork. |
| R2 | §17 similarity invites **look-ahead bias**; a leaky backtest would produce confident, wrong edge estimates | **High** | Spec §17.3 demands leakage prevention. Point-in-time feature store; grade only with data available at signal time. Defer to last. |
| R3 | Flow classification **fabricates institutional intent** — spec §32 explicitly forbids this | **High** | Deterministic rules first; store `excluded interpretations` + confidence; never assert intent the prints don't support. |
| R4 | `app.py` is 7,681 lines; more inline features worsen it | Med | Keep new work in `engine/` modules with `register_*_routes`, as 7.6 did. |
| R5 | **No migration framework**; §2.1 requires migrations | Med | Formalize the 7.6 `ALTER TABLE` pattern before Trade Cards land. |
| R6 | Flow P/L can **mislead** (spec §5.2/5.3) — a wide-spread mark or a hedge read as a naked directional bet | Med | Conservative executable mark default; label stale/wide; show intent uncertainty. |
| R7 | Multi-tab workspace is a large frontend lift against a 4,450-line `apex_os.js` | Med | Continue the self-contained band pattern (isolated `<style>` + IIFE). |
| R8 | QuantData key is `sync:false` — flow features silently degrade if unset | Med | Already surfaces `NOT_CONFIGURED`; extend to §2.4 vocabulary. |
| R9 | Scope: full APEX 9.0 is a multi-week program, not one session | **High** | Phase gates above; each independently deployable and reversible. |

---

## 10. Files that would be modified (per §32, before code changes)

**Phase 0a–0b (immediate, tiny):**
- delete `engine/contracts.py`, `engine/persistence.py`
- `tests/test_decision_intelligence.py` (inject events fixture)

**Phase 1 (flow foundation):**
- new: `engine/flow_classifier.py`, `engine/flow_clusters.py`, `engine/flow_routes.py`
- modify: `app.py` (import guard + `register_*_routes` only), `engine/flow_intelligence.py`
- modify: `ARCHITECTURE.md` (required by repo rule)

**Phase 2 (cards + P/L):**
- new: `engine/trade_cards.py`, `engine/flow_pl.py`, migration for `trade_cards`
- extend: `signal_evaluator.py` (reuse MFE/MAE), `app.py` (registration)

No production code was changed in Phase 0.

---

## 11. Recommendation

Do **not** run APEX 9.0 as written. It is a greenfield spec pointed at a mature
codebase, and taken literally it would rebuild a canonical bus, confluence
engine, decision engine, risk guard, trade coach, director, story, and replay
that all already work — the exact mistake `ARCHITECTURE.md` records for the last
three specs.

Run it instead as **four targeted additions** (flow classification/clustering,
flow P/L, Trade Cards, historical similarity) plus **one deletion** (the orphaned
`contracts.py`/`persistence.py` fork), sequenced as §8 above, each landing as a
read-only consumer of the existing bus.

Suggested first move: **Phase 0a + 1a** — delete the dead fork (fixing the
failing guard test) and build the flow classifier, which is the one piece the
spec is genuinely right that APEX lacks and which everything else in §§4–6
depends on.
