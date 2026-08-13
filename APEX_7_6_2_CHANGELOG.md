# APEX 7.6.2 — Alerts become order tickets

The 7.6.0 alert summarised the structure; it did not tell you what to *do* with
each leg. `Condor 7480.0/7490.0 — 7640.0/7650.0` leaves the reader to infer which
strikes are bought and which are sold — the one thing an alert must never make
you guess.

Alerts now spell out every leg as **action + strike + right**: `S 6270P` is sell
the 6270 put, `B 6260P` is buy the 6260 put.

| Structure | Ticket | Reading |
|---|---|---|
| Bull put credit | `S 6270P / B 6260P` | sell the higher put, buy the lower |
| Bear call credit | `S 6330C / B 6340C` | sell the lower call, buy the higher |
| Debit call | `B 6295C / S 6305C` | buy the nearer call, sell the further |
| Debit put | `B 6300P / S 6290P` | buy the higher put, sell the lower |
| Iron condor | `PUTS S 7490P / B 7480P` + `CALLS S 7640C / B 7650C` | wings labelled so the tested side is obvious |

Also added, all from fields the engine already produced and the old alert simply
discarded: net credit/debit, POP, risk/reward, max profit and max loss per
contract, breakeven (debits), and a context line with spot, expected move, VIX +
regime, and short delta. Strikes print as `6270`, not `6270.0`, and half-strikes
survive as `6272.5`. The time stop is now included, and the modeled-pricing
caveat rides along so a ticket is never mistaken for a live-chain fill.

Sample (the live 2026-07-15 condor, re-rendered):

    APEX ALERT — Premium Strategy
    SPX: Iron Condor · Confidence 78.0

    PUTS   S 7490P / B 7480P
    CALLS  S 7640C / B 7650C
    (10 wide each side)
    Net credit 3.20 · POP 72% · RR 0.47
    Max profit $320 · Max loss $680 (per contract)
    Spot 7565 · EM ±45 · VIX 18.2 MID

    Exit: Buy back at ~0.96 (capture 70-80% of credit).
    Stop: Close the tested side if price breaks either short strike (7490 / 7640)...
    Time: Flatten by ~3:30 PM ET ...

    Strikes/pricing modeled from expected move - verify on the live chain.

## Tests
8 new tests in `tests/test_premium_strategy.py` assert the exact leg strings for
all five structures. This mapping is safety-critical — a flipped B/S would enter
the inverse structure — so each direction is pinned by an explicit assertion
rather than left to review. Also covered: strike formatting, the modeled-pricing
caveat, and a sparse-legs case (the builder must never raise, since it runs on
the bus cycle). Suite: **210 passing**, 2 pre-existing permanent failures.
