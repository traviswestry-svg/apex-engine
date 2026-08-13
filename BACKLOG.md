# APEX — Backlog

> **What this is.** A living, sequenced punch-list. One short entry per item with
> a **status** and, where relevant, a **gate** (a condition that must be true
> before the item is worth building). Sequenced by value-over-risk, not by spec
> order.
>
> **Why it exists.** To stop re-litigating what's done and to prevent building
> ahead of what the data or a go-live decision can support. Check `ARCHITECTURE.md`
> for what exists; check here for what's next and whether it's ready.
>
> **Status legend:** ✅ done · 🟡 partial · ⬜ not started · 🔒 gated (can't
> meaningfully build yet — gate noted).

---

## Tier 1 — Foundation & correctness  → **COMPLETE**

| Item | Status | Notes |
|---|---|---|
| Active Trade Director position-truth bug | ✅ | Debounce no longer emits stale ENTER while a position is live. Fixed in `director/persistence.py` via `ENTRY_DIRECTIVES` bypass. Failing nested test now passes. |
| Remove dead duplicate modules | ✅ | Deleted `engine/apex_engines.py`, `engine/price_mapper.py`, `engine/trade_audit.py` (identical dead copies). Earlier: `engine/app.py` + 3 broker/risk dupes. |
| Architecture guard test | ✅ | `tests/test_architecture_canonical_imports.py` — canonical imports + no new duplicate modules/test-files. |
| Runtime health states | ✅ | `/health` returns `health_state` ∈ {CLOSED, WARMING, HEALTHY, STALE, DEGRADED}. Disambiguates closed-vs-stuck. |
| Market-closed planning mode (backend) | ✅ | `/api/overnight_briefing` assembles session + next-RTH + events + overnight plan + range into one payload with a headline. |
| Market-closed planning mode (frontend) | ⬜ | UI that renders the briefing instead of "LOADING". **Deferred deliberately** — needs live-render verification; do it where you can see it (DevTools at ~390px). |

---

## Tier 2 — Trading edge (analytics & learning)  → mostly 🔒 **DATA-GATED**

> **The gate:** these compute statistics over graded outcomes. The outcome
> pipeline (`signal_evaluator`, director `evaluator`) only started accumulating
> recently. Building the machinery is fine; *trusting the output* requires weeks
> of gated signals + graded directives. Until then, any number these produce is
> noise. Don't calibrate against an empty table.

| Item (maps to 8.0 phase) | Status | Notes / gate |
|---|---|---|
| Signal MFE/MAE evaluator | ✅ | `signal_evaluator.py` — single-window SPX MFE/MAE, WIN/LOSS/SCRATCH, `/api/signal_scorecard`. |
| Learning Engine: multi-horizon | ⬜🔒 | Extend evaluator to mark at 15/30/45-min horizons. Structure buildable now; **inert until data exists**. |
| Learning Engine: expectancy / profit factor / win-rate | ⬜🔒 | Aggregations over graded outcomes. **Gate: weeks of data.** |
| Confidence calibration | ⬜🔒 | "Confidence 91 → historically 84% over N samples, this setup/regime." The high-value one. **Gate: enough per-bucket samples.** `institutional_intelligence` already stores ici alongside outcomes to enable this. |
| Setup-family analytics | ⬜🔒 | Win-rate by setup type / session segment / gamma regime. **Gate: data.** |
| Trade execution review (option-fill quality) | ⬜🔒 | Needs *option* fill data (bid/ask/slippage), not just SPX points. **Gate: capturing option fills** — not currently stored. |
| Confluence synthesizer | ✅ | `confluence.py` — long/short setup scorecard, conviction-gated. Weights are hand-set (unvalidated); tune against outcomes later. |
| Decision Intelligence panel | ✅ | `decision_intelligence.py` — six-question read + confidence pyramid; TRADE/WATCH/AVOID calibrated to gate discipline. |

---

## Tier 3 — Live trading hardening  → 🔒 **GO-LIVE-GATED**

> **The gate:** none of this matters unless real orders flow through APEX. If it
> stays a decision-support tool traded manually, Tier 3 is optional *forever* —
> a legitimate end state. **But the moment one live order is wired, the risk
> items below become Tier 0 / mandatory, not optional.** Do NOT build these
> speculatively — unexercised risk code gives false confidence.

| Item | Status | Notes |
|---|---|---|
| Server-side risk enforcement (complete) | 🟡🔒 | `trade_risk_guard` covers whitelist, spread, quote-age, premium, cooldown, session, fail-closed. **Missing enforcement:** daily-loss (declared but not wired into `validate_entry`), consecutive-loss lockout, one-position-at-a-time, kill-switch, aggregate exposure. **Mandatory before live.** |
| E*TRADE lifecycle hardening | 🟡🔒 | Adapter + preview/place/reconcile scaffolded. Needs OAuth-expiry handling, idempotency, partial-fill handling. |
| Order idempotency | ⬜🔒 | Client-request dedup so a retry can't double-fill. |
| Broker reconciliation | ⬜🔒 | Reconcile APEX position truth vs broker truth; lockout on mismatch. |
| Restart recovery | ⬜🔒 | Recover active-position/order state after a process restart. |
| Durable execution state | ⬜🔒 | Execution state survives restart (ties to Tier 4 Postgres). |

---

## Tier 4 — Long-term infrastructure  → ⬜ **DESTINATION, not a task**

> Not a capability gap today. With a mounted Render disk, SQLite-on-disk is a
> reasonable persistence layer for a single-instance app for a long time.

| Item | Status | Notes |
|---|---|---|
| PostgreSQL migration | ⬜ | Becomes real with concurrent writers or Tier 3 durability needs. Not before. |
| Distributed / multi-instance readiness | ⬜ | Only if you outgrow one instance. |
| Advanced replay & research tools | ⬜ | Replay exists; "2.0" (synchronized multi-stream) is enhancement, low urgency. |

---

## 8.0 phases already done or partly done (don't re-spec these)

From the 8.0 prompt, these are **already built** this session-chain — verify in
`ARCHITECTURE.md` before specifying:

- **#8 Overnight Intelligence** → `overnight.py` + `/api/overnight_briefing` (✅)
- **#13 Market Closed Mode** → backend ✅ (`/api/overnight_briefing`), frontend ⬜
- **#12 Story Engine 2.0** (what/why/evidence/contradiction) → `story.py` already
  narrates confirm/diverge/contradiction; Decision panel adds the six-question
  structure (🟡 — core done, "2.0" polish open)
- **#10 Learning Engine (MFE/MAE)** → `signal_evaluator.py` foundation ✅, rest 🔒
- **#11 Mission Control contradicting-evidence** → Decision panel surfaces
  missing-confirmations / contradictions (🟡)

Genuinely new in 8.0 (not yet built): Dealer Intelligence 2.0 (#1), Liquidity
Engine (#2), Flow Intelligence 2.0 (#3), WebSocket conversion (#4), Contract
Intelligence (#5), Execution-quality-before-entry (#6), Benzinga Catalyst
Engine (#7), Replay 2.0 (#9), perf/snapshot optimization (#14). **Sequence these
by the gates above** — several (learning-adjacent) are data-gated; contract/
execution/liquidity are most valuable if you head toward live trading.

---

## The single most important non-code item

**Let outcome data accumulate.** Nearly every high-value Tier 2 item, and the
eventual tuning of the confluence/decision weights, is gated on it. The best
"next action" for weeks is often *not building* — it's letting Monday's gated
signals fill the tables so the learning surfaces have real numbers. Motion ≠
progress; data is what turns these heuristics into measured edge.
