# APEX 7.7 — Premium structures priced from the live chain

**Status:** complete. Full suite **571 passed / 0 failed** (was 544). 27 new tests.
**Fixes:** a live alert that recommended a trade which could not profit.

---

## The bug

APEX alerted, at 1:19 PM ET on 2026-07-17:

    SPX: Iron Condor · Confidence 71.0
    PUTS S 7400P / B 7390P · CALLS S 7570C / B 7580C
    Net credit 3.30 · POP 69% · RR 0.49
    Max profit $330 · Max loss $670

The live ticket for those exact strikes:

| | APEX | Reality |
|---|---|---|
| Net credit | **3.30** | **−0.10 (a DEBIT)** |
| Max profit | $330 | **$0** |
| Max loss | $670 | **$1,010** |

You would pay to enter, and the best case is losing the debit. Every economic
field was fabricated.

## Two errors, stacked

**1. The expected move never decayed.**

```python
em = price * (vix / 100.0) / math.sqrt(252.0)   # a FULL DAY's move
sigma = em                                       # used unscaled at 1:19 PM
p_itm = 1.0 - _phi(distance / sigma)
c = width * p_itm * rich
```

Reproduced exactly: 7486.43 × 0.1788 ÷ √252 = **84.32**, the alert's printed EM.
At 1:19 PM only 161 of 390 minutes remained, so σ should have been **54.2**. The
model believed the 7570 call sat at ~1.0σ (16% ITM odds) when it was ~1.55σ (6%).
**The error grows through the session** — worst exactly when a 0DTE condor is most
likely to be considered.

**2. It modelled what it could read.**

Even time-corrected, the model says ~1.25 and reality is 0.00: both call legs
quoted **0.10 × 0.15**. Ten points apart, both pinned at the minimum tick, the
vertical collects nothing. No value of σ recovers that — the information was never
in the model, it was in the chain.

`flow_pl` settled this in Step 4: mark from the chain, at conservative executable
levels. The premium engine was the last module still guessing at prices it could
look up — and it pushed verification onto the human ("verify on the live chain")
at the exact moment the output looked most authoritative.

**The credit-quality floors could not save you.** `_MIN_CREDIT_RATIO = 0.12` and
`_MIN_RR = 0.15` are real checks, and modelled 3.30/10 = 33% sails through. Real
0.00/10 = 0% is rejected instantly. The gate worked; it was fed fiction.

## The fix

**`engine/premium_chain_pricing.py`** (new) — prices a built structure from the
chain at the executable convention, matching `flow_pl`'s CONSERVATIVE default:

    SELL a leg -> you receive the BID
    BUY  a leg -> you pay the ASK

Never mid. A midpoint credit is a price nobody fills, and 0DTE wings are exactly
where the mid lies most. If **any** leg lacks a two-sided market the structure is
UNPRICEABLE — a partially-priced spread is not a cheaper spread, it is an unknown
one.

**Selection and pricing are now separate concerns.** "Balanced auction favours a
condor" is a legitimate model conclusion needing no chain. "Net credit 3.30" is
not. So:

- the strategy and strikes survive as a **candidate**;
- economics are **stripped**, not stamped — `Net credit 3.30 · Max profit $330`
  reads as fact regardless of any `pricing_basis` note beneath it;
- `tradeable: false`, and **the alert dispatcher refuses to fire**.

When the chain does price it, the model's economics are **replaced, not averaged**.
The model chose the strikes; it gets no vote on what they are worth. The modelled
figure is retained only as `modeled_credit_for_reference`.

## Behaviour, on a realistic 0DTE book

| Time | Strikes chosen | Modelled credit | **Executable credit** |
|---|---|---|---|
| 09:45 | P 7405/7395 · C 7570/7580 | 3.02 | **+1.40** |
| 1:19 PM | P 7430/7420 · C 7540/7550 | 2.94 | **+1.80** |
| 3:15 PM | P 7460/7450 · C 7515/7525 | 3.20 | **+2.15** |

The wings now **tuck in** as the session shortens — 1σ at 1:19 PM is 54 points,
not 84. And the model still overstates by 40–100% even after the time fix, which
is precisely why it may choose strikes but never price them.

## 🐛 Two further bugs found while fixing this

**Short strikes rounded TOWARD spot.** `_round_strike` rounds to nearest, so a
6273.1 target landed on **6275** (0.93σ, POP 0.647) instead of **6270** (1.07σ,
POP 0.716) — silently raising assignment risk and cutting POP below its own floor.
Fixed at source with `_round_short_away`: a short strike now rounds away from the
money, the only direction that cannot make the position riskier than specified.
Long strikes still round nearest; they only cap risk.

**A reporting contradiction.** POP `0.647` printed as `"Modeled POP 65% below the
65% floor."` The message compared at 3 decimals and displayed at 0. Now shows the
precision it compares at.

## Files

**Added:** `engine/premium_chain_pricing.py`, `tests/test_premium_chain_pricing.py` (24 tests), `APEX_7_7_CHANGELOG.md`

**Modified:**
- `engine/premium_strategy.py` — `scale_sigma_to_session`, `session_minutes_left`,
  `_round_short_away`, `_apply_chain_pricing`, `chain_fetcher`/`now_et`/`symbol`/
  `expiration` params, `tradeable` + `economics_available` on the panel,
  `VERSION` → `7.7.0_PREMIUM_CHAIN_PRICED`.
- `engine/premium_strategy_routes.py` — `chain_fetcher` threaded to both call
  sites; `_expiration_for`; clock resolved **before** the panel is built; **alert
  dispatch gated on `tradeable`**.
- `app.py` — passes the existing `_poly_chain_fetcher` to both.
- `tests/test_premium_strategy.py` — harness now supplies a realistic Black-Scholes
  chain; +3 regression tests.

**No new provider, no E*TRADE connection, no new subscription.** E*TRADE is a
broker adapter (execution), never a market-data path. The chain APEX needed was
already wired for `flow_pl`.

## Tests

| Concern | Tests |
|---|---|
| **the real ticket prices as a debit, not a $330 credit** | 2 |
| executable convention (sell→bid, buy→ask); never mid | 2 |
| missing leg / one-sided / crossed / no fetcher / broken fetcher → unpriceable | 5 |
| one chain fetch per side | 1 |
| a genuine credit prices as a credit | 1 |
| `session_minutes_left`, √t scaling, close→0, EM 0 | 4 |
| **no chain → no economics, but strikes survive; not tradeable** | 3 |
| chain price overwrites the model, never averages | 1 |
| strikes tuck in as the session shortens | 1 |
| **dispatch refuses to alert without a chain price** | 2 |
| short strikes round away from spot | 1 |

## Rollback

Revert the four files. `PREMIUM_NO_PREMIUM_BID` (default 0.10) is the only new
env var. Note the routes now depend on `premium_chain_pricing`, so reverting one
requires reverting both.

## Known limitations

1. **Chain latency.** If your Polygon plan is delayed rather than real-time,
   credits are stale by that delay — but staleness is *detectable* where a model
   error is not, and the new chain-quality gate is exactly the instrument for it.
2. **POP is still modelled.** Credit, max profit/loss and RR are executable; POP
   remains a normal-distribution approximation on the scaled σ. It should
   eventually come from chain deltas.
3. **`_expiration_for` assumes 0DTE** unless the bus says otherwise — consistent
   with the exit plan ("flatten by 3:30 PM — 0DTE theta/gamma cliff"), but it is
   an assumption.
4. **The chain-quality gate is not yet consulted here.** A structure priced off a
   DEGRADED chain is currently treated the same as one off a HIGH chain. That is
   the natural next step — and now it has something real to gate.
