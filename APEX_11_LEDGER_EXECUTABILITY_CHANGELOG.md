# APEX 11 — Executability Gate on the Recommendation Ledger

**Status:** complete. Full suite **902 passed / 0 failed** (+4).
**Context:** this ports the calibration-integrity rule onto the *better* capture
system this tree already has, rather than adding a parallel one.

---

## What I found reviewing the ZIP

This tree is well ahead of my incremental line — 129 engine modules, the full 11.1
historical layer (calibration, similarity, research lab, replay), and a
`recommendation_ledger` that is a *stronger* capture system than the schema extension
I had built separately. The ledger records decision-time economics immutably, hashed
and deduplicated, with provenance: `entry_credit`, `chain_grade`, `pricing_basis`,
`execution_confidence`, quote-age stats, confidence decomposition. Whoever built it
went further than my version did.

So the right move was **not** to port my `premium_recommendations` schema (the ledger
supersedes it). It was to close the one gap the ledger still had.

## The gap

The ledger captured everything needed to grade against executable reality — but
nothing enforced that at the *settlement* end. `append_event(..., "GRADED", {...})`
wrote whatever `outcome_label` and `realized_pnl` the caller passed. So an
unexecutable trade — the broken-condor class, unpriceable or modeled-only — could
still be settled as a directional WIN, and `calibration_readiness` counted every
settled row as gradeable history.

This is exactly the roadmap's warning: *"calibration must be performed against 'did
this recommendation produce executable profit', not 'did the thesis happen'."* The
capture was honest; the settlement path wasn't guarded.

## The fix — two edits, both at the settlement boundary

**1. Executability gate in `append_event`.** When a CLOSED/SETTLED/GRADED event
carries an outcome, the ledger now checks whether the recommendation was executable
at entry — read from the *immutable capture*, so the settlement caller cannot bypass
it. `_row_executable` requires: tradeable, priced `live_chain_executable` (not
unpriceable/modeled), and a positive credit. If not, the label is forced to
`NOT_EXECUTABLE` with P/L 0, whatever the caller passed.

**2. `NOT_EXECUTABLE` excluded from the gradeable count.** `counts()` previously
treated every settled row as gradeable. It now subtracts `not_executable`, so
`calibration_readiness` reflects real executable history — calibration won't think it
has 50 samples when some were never fillable.

## Proven end-to-end

```
executable condor   -> settle WIN +180   -> kept:  WIN, +180
unpriceable condor  -> settle WIN +330   -> forced: NOT_EXECUTABLE, 0
counts: total 2, gradeable 1, not_executable 1
```

The unpriceable trade cannot become a win no matter what the settler passes, and it
does not inflate the calibration sample count.

## A bug this caught

The tree's own test fixture stores `pricing_basis: "LIVE_CHAIN_EXECUTABLE"` in
**uppercase**. A case-sensitive guard would have silently treated every real trade as
non-executable and forced everything to NOT_EXECUTABLE — the opposite failure, and a
quiet one. The guard lowercases before comparing; a test pins this.

## Files

**Modified:** `engine/recommendation_ledger.py` — `_row_executable` / `_row_field`
helpers; executability gate in `append_event`; widened its SELECT to read the
executability columns; `not_executable` in `counts()`.
**Tests:** `tests/test_recommendation_ledger.py` (+4).

## Backward compatibility

- No schema change — the guard reads columns the ledger already captured.
- Executable trades settle exactly as before.
- Existing ledger tests (3) still pass unchanged.

## What this leaves

The ledger now captures *and* grades honestly. What still doesn't exist is an
automated settler that fills `realized_pnl` from closed-session chains — outcomes are
recorded via `append_event` by whatever calls it. When that settler is built (the
natural next step, and it needs closed-session option marks), the executability gate
is already in front of it, so it cannot violate the rule by construction.
