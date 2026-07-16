# APEX 9 — Step 4: Theoretical Flow P/L

**Status:** complete. Full suite **374 passed / 0 failed** (was 319). 55 new tests.
**Gate:** P/L tests pass → Step 5 (feature store + similarity) is unblocked, pending your go-ahead.

---

## Architectural rationale

P/L is a read-only consumer of the Step 2→3 pipeline plus the **existing** options
chain. Nothing upstream changed: `flow_tape.py`, `flow_classifier.py`,
`flow_clusters.py`, and `options_data_bus.py` all have **zero** references to
`flow_pl`. `/api/flow_tape`, `/api/flow_classifier`, `/api/flow_clusters` keep
their exact shapes.

Chain access is **injected**, reusing the same `_poly_chain_fetcher` app.py
already wires for the Trade Command Center — not a second path to the provider.
If that fetcher failed to wire, P/L degrades to unmarkable rather than raising
(`globals().get("_poly_chain_fetcher")`).

Normalization reuses `options_data_bus.normalize_chain`, which already derives
mid / spread% / liquidity score / quote age. Re-implementing that math here is
exactly the drift `ARCHITECTURE.md` warns about.

---

## The honesty model (this is the whole point of the step)

`entry_mark` is the **print's observed execution price** — a fact, not a model.
We never had the quote at trade time and do not pretend to reconstruct one.

`current_mark` comes from the live chain by one of five methods:

| Method | Meaning |
|---|---|
| `bid` | what you'd receive selling into the bid |
| `ask` | what you'd pay lifting the ask |
| `midpoint` | (bid+ask)/2 — flattering on wide markets |
| **`conservative_executable_mark`** | **DEFAULT.** Marks at the side you must trade against to CLOSE: a long marks to the BID, a short to the ASK. Always the worse side, deliberately. |
| `theoretical_value` | Black-Scholes on chain IV. Modelled, and stamped as such. |

**Why conservative is the default.** On a 0.05 x 5.00 market the midpoint is
2.525 — a price no one can transact at. Midpoint marking manufactures paper
profit exactly where liquidity is worst, which is exactly where a trader most
needs the truth. `test_midpoint_inflates_pl_on_a_wide_market_and_conservative_does_not`
pins the difference; the mutation that flips the default to midpoint breaks
**11 tests**.

**Direction comes from observed aggression**, not assumption: at/above ask →
LONG, at/below bid → SHORT. A **midpoint fill has no observable initiator, so no
P/L is computed at all** — a signed number there would be a coin flip dressed as
analysis. Verified live: the MID print in the end-to-end run reports
`UNAVAILABLE`, not a guess.

**Multiplier is inferred, not assumed.** No feed in this codebase supplies one.
Assuming 100 is right for standard contracts and silently 10× wrong for adjusted
ones, so it is derived from the provider's own arithmetic
(`premium / (trade_price × contracts)`), matched against 100/10/1000/1, and
**warned about** when non-standard or uninferable.

## What still cannot be known (declared, never faked)

| Unknown | How it's handled |
|---|---|
| IV / spot at trade time | The chain gives IV *now*. Excursions and IV/spot deltas are measured from **first observation** and every field says so (`iv_change_since_first_observation`, `underlying_move_since_first_observation`, `excursion_basis`). |
| Package construction | An uncertain spread/roll is **never** reported as a naked directional position — an explicit warning fires instead (below). |
| Contracts outside the chain window | The chain fetcher uses ±5% of spot (`POLYGON_STRIKE_WINDOW_PCT`). Strikes outside it have **no quote** and are reported unmarkable, not estimated. Verified live: the 6900 print with spot 6300 (+9.5%) returns `UNAVAILABLE`. |
| Opening vs closing | Still excluded (Step 2 — no open interest). P/L describes the print, not a position. |

### The required label

    Theoretical directional P/L based on observed prints; actual position
    structure and realized performance are unknown.

Emitted verbatim on every event payload, every cluster payload, and `/health`.

### The package-construction warning

Spec: *"avoid treating an uncertain spread or roll as a naked directional
position; display a warning when the true package construction is unknown."*
`package_construction_known: false` fires when Step 3's cluster carries
`spread_leg_candidate` / `likely_roll` members or `intent_uncertainty ≥ 0.4`,
with:

> True package construction is unknown. Some member prints pair with other
> strikes or expirations, so this cluster may be a leg of a spread or a roll
> rather than a naked directional position — in which case the P/L below does
> not describe the participant's actual risk.

Deleting that logic breaks 2 tests.

---

## 🐛 Gap found during end-to-end verification

The first pipeline run priced **1 cluster** and silently ignored everything else.
The spec says *"theoretical P/L for qualifying individual events **and**
clusters"* — but singletons (single prints below `min_prints`) were never priced.
That hid precisely the cases that matter most: the far-strike print with no
quote, the midpoint print with no observable side, and the lone PUT block.
Fixed: `single_events` are now priced alongside clusters. The unit tests passed
throughout — only running the real pipeline exposed it.

## Files

**Added**
- `engine/flow_pl.py` — marks, P/L, cluster aggregation (pure; no I/O; never raises).
- `engine/flow_pl_store.py` — MFE/MAE persistence + migration (non-fatal).
- `engine/flow_pl_routes.py` — `/api/flow_pl`, `/api/flow_pl/health`, chain cache.
- `tests/test_flow_pl.py` — 55 tests.
- `APEX_9_STEP_4_CHANGELOG.md`

**Modified**
- `app.py` — non-fatal import guard, registration reusing `_poly_chain_fetcher`,
  `VERSION` → `9.4.0_FLOW_PL`.

**Deleted:** none. **Upstream modified:** none.

## Metrics emitted

Required, per event: `entry_mark` · `current_mark` · `estimated_pl_dollars` ·
`estimated_return_pct` · `mfe_dollars` · `mae_dollars` · `time_to_mfe_seconds` ·
`time_to_mae_seconds` · `underlying_move_since_first_observation` ·
`iv_change_since_first_observation` · `spread_width` · `quote_freshness_seconds` ·
`liquidity_quality` · `mark_methodology` — plus `position_side`, `multiplier`,
`markable`, `warnings`, `label`.

Per cluster: `weighted_entry_mark` / `weighted_current_mark` (**contract-weighted**,
per spec) · aggregate `estimated_pl_dollars` · `cost_basis_dollars` ·
`marked_member_count` / `unmarked_member_count` · `package_construction_known` ·
`intent_uncertainty` · **`members[]` with each member's own entry timestamp, entry
mark, and member-level P/L preserved**.

## Tests — every required case

| Required case | Test |
|---|---|
| wide bid/ask spreads | `test_midpoint_inflates_pl_on_a_wide_market_and_conservative_does_not`, `test_wide_spread_is_warned_under_any_method` |
| stale quotes | `test_stale_quote_is_flagged`, `test_fresh_quote_is_not_flagged_stale` |
| halted or illiquid contracts | `test_illiquid_contract_is_flagged`, `test_halted_contract_with_no_quote_is_unmarkable` |
| partial cluster formation | `test_partial_cluster_marks_only_what_it_can_and_says_so`, `test_cluster_with_no_markable_members_reports_none_not_zero` |
| missing quotes | `test_no_contract_at_all_is_unmarkable_not_zero`, `test_missing_bid_makes_a_long_unmarkable_under_conservative` |
| expired contracts | `test_expired_contract_detected`, `test_years_to_expiry_is_none_for_expired`, `test_zero_dte_still_has_nonzero_time_value` |
| assignment of late prints | `test_late_print_is_tracked_independently` |
| changing option multipliers | `test_standard_multiplier_inferred_silently`, `test_nonstandard_multiplier_is_inferred_and_warned`, `test_uninferable_multiplier_falls_back_and_warns`, `test_odd_multiplier_falls_back_and_warns_about_misscaling`, `test_multiplier_is_applied_to_pl` |
| extreme volatility | `test_extreme_move_does_not_break_pl`, `test_extreme_iv_does_not_break_theoretical_mark`, `test_negative_and_garbage_inputs_never_raise` |
| zero-bid contracts | `test_zero_bid_marks_a_long_to_zero_and_warns` |
| midpoint inflation | `test_midpoint_inflates_pl_on_a_wide_market_and_conservative_does_not` |

Plus MFE/MAE store (7 tests), all five mark methods, direction resolution,
cluster weighting, the required label, and the forbidden-language guard.

### Mutation-tested

| Injected fault | Caught by |
|---|---|
| default to MIDPOINT instead of conservative | **11 tests** |
| compute P/L for UNKNOWN side (guess direction on mid fills) | 2 tests |
| assume multiplier 100 always | 3 tests |
| report unmarkable cluster P/L as `0.0` instead of `None` | `test_cluster_with_no_markable_members_reports_none_not_zero` |
| drop the package-construction warning | 2 tests |

`0.0` vs `None` matters: a flat P/L and an unknown P/L are different claims, and
conflating them would put a confident zero on a dashboard where the truth is
"we can't see this."

## Test results

    pytest tests/test_flow_pl.py -q  ->  55 passed
    pytest -q                        -> 374 passed, 0 failed
    architecture guard               ->  26 passed

**End-to-end on realistic provider rows through the real normalizer:**
cluster (3/3 marked) +$226,000 · PUT block −$156,000 · MID print `UNAVAILABLE`
(no observable side) · 6900 strike `UNAVAILABLE` (outside chain window) ·
**2 chain fetches for 6 prints**.

## Performance benchmarks

| rows | classify | cluster | P/L | total | chain fetches |
|---:|---:|---:|---:|---:|---:|
| 50 | 1.9 ms | 1.3 ms | 0.8 ms | **4.0 ms** | 4 |
| 200 | 6.1 ms | 3.7 ms | 2.8 ms | **12.6 ms** | 4 |
| 500 | 16.5 ms | 8.5 ms | 8.7 ms | **33.7 ms** | 4 |
| 1000 | 33.5 ms | 23.7 ms | 15.4 ms | **72.7 ms** | 4 |
| 2000 | 61.3 ms | 33.5 ms | 26.4 ms | **121.2 ms** | 4 |

**Chain fetches stay flat at 4** regardless of print count — they scale with
distinct `(ticker, expiration, side)` groups, not contracts, because `get_chain`
returns a whole chain and it is cached per request. At 2000 prints across two
expirations × two sides that is 4 HTTP calls, not 2000. This was the central
design concern raised at the end of Step 3, and it is resolved.

CPU cost above excludes provider latency, which will dominate in production.

## Migrations

**First stateful step.** New table `flow_pl_tracking` (event_id PK, cluster_key,
session_date, entry/first-seen baselines, mfe/mae + timestamps, samples), created
at registration via `CREATE TABLE IF NOT EXISTS` with forward-compatible
`ALTER TABLE ADD COLUMN` migration — the same pattern as 7.6. Indexed on
`cluster_key` and `session_date`. Lives in `DB_PATH` (`/data/apex_tracking.db` on
Render, persistent disk).

Init failure is non-fatal: tracking disables itself and P/L still serves live
marks (`tracking: false`).

## Feature flags

| Flag | Default | Effect |
|---|---|---|
| `FLOW_PL_ENABLED` | `true` | off → route returns `available:false` |
| `FLOW_PL_MARK_METHOD` | `conservative_executable_mark` | default marking method |
| `FLOW_PL_DEFAULT_MULTIPLIER` | `100` | fallback when uninferable |
| `FLOW_PL_STALE_QUOTE_S` | `60` | quote age before STALE warning |
| `FLOW_PL_WIDE_SPREAD_PCT` | `25` | spread% before WIDE warning |
| `FLOW_PL_ILLIQUID_SCORE` | `35` | liquidity score below which we warn |
| `FLOW_PL_RISK_FREE` | `0.04` | rate for the theoretical mark only |

`?method=` overrides per request; an unknown method is rejected with the valid
list rather than silently falling back.

## Rollback

1. `FLOW_PL_ENABLED=false` — instant, no deploy. Table remains but is not written.
2. Full: delete `engine/flow_pl.py`, `engine/flow_pl_store.py`,
   `engine/flow_pl_routes.py`, `tests/test_flow_pl.py`; revert the `app.py` guard
   + registration + `VERSION`.
3. Schema: `DROP TABLE flow_pl_tracking;` — no other table references it, and
   nothing else reads it. Dropping loses only accumulated MFE/MAE history.

## Known limitations

1. **MFE/MAE are only as dense as the sampling.** Excursions come from recorded
   samples, so the true intraday extreme between samples is invisible. Today the
   only sampler is the `/api/flow_pl` request itself — **so excursions accumulate
   only while someone is polling the endpoint.** A scanner-side sampler (as 7.6
   does for premium grading) would fix this; deliberately not added here to keep
   Step 4 scoped. **This is the most important gap to close before Step 5 relies
   on MFE/MAE as labels.**
2. **`entry_spot` / `entry_iv` are captured at first observation**, not at the
   print. Seconds-to-minutes of drift is baked in and labelled, not corrected.
3. **±5% strike window.** Far-OTM prints — often the most interesting flow — are
   unmarkable. Widening `POLYGON_STRIKE_WINDOW_PCT` costs chain size; it is a
   deliberate trade-off, not an oversight.
4. **Theoretical mark uses chain IV**, which is itself a vendor model. It is
   offered because the spec requires it, defaults off, and is stamped
   model-derived.
5. **Multiplier inference is circular when the provider omits premium** —
   `flow_tape` then computes `premium = price × size × 100`, so the ratio returns
   100 by construction. Real multipliers are only detectable when the provider
   supplies premium directly.
6. **No UI surface yet** — endpoint only, per the approved sequence.

## Next dependency

**Step 5 — Historical feature store + similarity engine.** Do not begin until you
confirm; the spec requires classification, clustering, and P/L results to be
*stable* first, and limitation 1 above is directly relevant: Step 5's leakage
controls explicitly forbid MFE/MAE in pre-decision features, and Step 5's labels
would be built from exactly the excursion data that is currently sampled only on
request.

Recommended before Step 5:
- add scanner-side sampling so MFE/MAE reflect the session, not the polling pattern;
- let the P/L run across a few live sessions so the store holds real data to
  validate leakage tests against, rather than synthetic fixtures.
