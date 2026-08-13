# APEX 9 — Step 2: Flow Classifier

**Status:** complete. Full suite **271 passed / 0 failed** (was 221). 50 new tests.
**Gate:** classifier tests pass → Step 3 (clustering) is unblocked.

---

## Architectural rationale

The Phase 0 audit found flow ingestion exists (`flow_tape.py`, `flow_intelligence.py`)
but classification does not. This step adds the missing layer **without touching
ingestion**: `flow_classifier` is a read-only consumer of the already-normalized
tape rows, integrated exactly like `premium_strategy` (pure engine module +
`_routes` module + non-fatal import guard in `app.py`). `flow_tape.py` has zero
references to the classifier; `/api/flow_tape` is byte-for-byte unchanged.

### The three certainty layers (the point of the whole module)

The spec's core rule is that observable facts, derived classifications, and
intent hypotheses must not be stored as though they carry equal certainty. They
are three separate fields:

| Layer | Field | Certainty |
|---|---|---|
| 1. Observable | `observable_facts` | copied from the provider; zero inference |
| 2. Derived | `classification`, `execution_aggression`, `size_class`, `directional_bias` | deterministic rules over layer 1 |
| 3. Hypothesis | `possible_intents[]` (+ `confidence`, `basis`), `excluded_intents[]` | never asserted; always plural |

    Observable fact:    trade_side_code=ABOVE_ASK, consolidation_type=SWEEP
    Derived:            SWEEP / AGGRESSIVE_BUY / BULLISH lean (conf 0.60)
    Intent hypothesis:  possible_directional_position (0.45) — "not evidence of
                        the buyer's net exposure"

Deterministic rules only. No model-based classification was added, per spec.

---

## What the data actually supports (verified, not assumed)

Verified against the live provider payload rather than the spec's field wishlist:

**Available per print:** ticker · contract_type · strike · expiration · premium ·
trade_price · contracts · `trade_side_code` (ABOVE_ASK/AT_ASK/MID/AT_BID/BELOW_BID)
· `consolidation_type` (SWEEP/BLOCK/SPLIT) · time_et.

**Not available — and therefore never inferred:**

| Missing | Consequence (handled honestly) |
|---|---|
| **open interest** | opening vs closing is **impossible** to derive → both are permanently in `excluded_intents` with a stated reason, plus a warning. Never guessed. |
| exchange sequence / count | a SWEEP is taken as **provider-reported**, not re-derived. `exchange_count` is recorded as `None`, not fabricated. |
| quote at trade time | no spread-quality or "stale quote" claims. Freshness is inferred only from **print age**, which is what we actually have. |
| per-print IV / Greeks | no IV-contribution or delta-attribution claims. |

Absent fields are recorded explicitly as `None` in `observable_facts` so
downstream code can never read silence as zero.

## ⚠️ A hazard found upstream — deliberately not inherited

`flow_tape._classify_row` contains this fallback:

```python
if not trade_side_code:
    aggressor = "BUY" if contract_type == "CALL" else "SELL" if contract_type == "PUT" else "NEUTRAL"
```

That **fabricates an aggressor from the contract type** — a guess wearing the
costume of a fact, and precisely what the Step 2 language rule forbids. It is why
this classifier does **not** consume `aggressor_side` or `tape_label` at all; it
reads `trade_side_code` directly. When the code is absent the result is
`UNKNOWN_AGGRESSION`, `data_quality: DEGRADED`, `directional_confidence: 0.0`,
and `directional_interpretation_uncertain`.

`test_missing_trade_side_code_yields_unknown_not_a_guess` pins this. I did **not**
change `flow_tape.py` — that would alter existing tape behaviour, outside this
step's boundary. **Recommended follow-up:** the same fallback still colours
`aggressor_side` / `tape_label` on `/api/flow_tape` and the dashboard tape panel.

---

## Files

**Added**
- `engine/flow_classifier.py` — the engine (deterministic, never raises, no I/O).
- `engine/flow_classifier_routes.py` — `/api/flow_classifier`, `/api/flow_classifier/health`.
- `tests/test_flow_classifier.py` — 50 tests.
- `APEX_9_STEP_2_CHANGELOG.md`

**Modified**
- `app.py` — non-fatal import guard, route registration with **injected**
  providers (`_fc_flow_tape` closes over the existing `_fetch_flow_tape_rows` +
  `build_flow_tape`, so the classifier never calls a provider itself), `VERSION` →
  `9.2.0_FLOW_CLASSIFIER`.

**Deleted:** none.
**Upstream ingestion modified:** none (`flow_tape.py` untouched, 0 references).

## Output contract

Every required field is emitted: `event_id` · `ticker` · `timestamp` ·
`classification` · `classification_confidence` · `directional_bias` ·
`directional_confidence` · `execution_aggression` · `possible_intents` ·
`excluded_intents` · `evidence` · `warnings` · `data_quality` ·
`classifier_version` — plus `observable_facts` (layer 1) and `size_class`.

**Classifications:** `SWEEP` · `BLOCK` · `SPLIT` · `SINGLE_LEG` · `AMBIGUOUS`
(structure) — `INSTITUTIONAL_SIZE` · `MID_SIZE` · `RETAIL_SIZE_NOISE` (size).
**Intents (hypotheses):** `spread_leg_candidate` · `likely_roll` ·
`possible_hedge` · `possible_directional_position` · `possible_volatility_trade` ·
`directional_interpretation_uncertain`.
**Always excluded:** `possible_opening_transaction` · `possible_closing_transaction`.

`event_id` is a deterministic SHA-1 of identifying fields only — never derived
values — so ids stay stable across classifier versions, supporting replay and
Step 3 cluster membership.

## Tests — every required case

| Required case | Test |
|---|---|
| ask-side sweeps | `test_ask_side_sweep_is_aggressive_buy_and_bullish_lean`, `test_at_ask_sweep_is_buy_not_aggressive_buy` |
| bid-side sweeps | `test_bid_side_call_sweep_leans_bearish`, `test_bid_side_put_sweep_leans_bullish`, `test_ask_side_put_sweep_leans_bearish` |
| blocks | `test_block_classification` |
| split prints | `test_split_classification` |
| same-timestamp multi-exchange | `test_same_timestamp_multi_exchange_sweep_is_provider_reported_not_inferred` |
| multi-leg candidates | `test_spread_leg_candidate_detected_and_dampens_directional_confidence`, `test_spread_candidate_carries_related_event_ids_for_auditability`, `test_volatility_structure_candidate_call_plus_put_same_expiry` |
| rolls | `test_likely_roll_needs_opposing_print_in_another_expiration`, `test_no_roll_when_same_expiration`, `test_no_roll_when_outside_pair_window`, `test_unrelated_prints_are_not_forced_into_a_relationship` |
| likely hedges | `test_possible_hedge_is_low_confidence_and_states_it_is_indistinguishable`, `test_hedge_hypothesis_coexists_with_directional_hypothesis`, `test_retail_put_buy_raises_no_hedge_hypothesis` |
| ambiguous midpoint | `test_midpoint_execution_is_directionally_uncertain` |
| stale quotes | `test_quote_at_trade_is_absent_so_no_spread_quality_claim` (no quote data exists → no false claim) |
| missing open interest | `test_opening_and_closing_are_always_excluded_never_guessed`, `test_open_interest_recorded_as_absent_not_zero` |
| delayed prints | `test_delayed_print_is_flagged_and_downgrades_quality`, `test_fresh_print_is_not_flagged_delayed` |
| zero-volume / malformed | `test_malformed_events_are_ambiguous_and_degraded` (5 cases), `test_classifier_never_raises_on_garbage` |
| classification versioning | `test_every_event_is_version_stamped`, `test_event_id_is_deterministic_across_runs`, `test_event_id_changes_when_identifying_fields_change`, `test_event_id_is_independent_of_derived_fields` |

Plus the language/architecture guards: `test_three_certainty_layers_are_stored_separately`,
`test_no_intent_is_ever_asserted_with_certainty`,
`test_forbidden_marketing_language_never_appears`,
`test_classify_batch_does_not_mutate_caller_rows`.

### Mutation-tested (the tests were verified to actually bite)

A green suite proves nothing on its own, so three deliberate regressions were
injected and confirmed caught, then reverted:

| Injected fault | Caught by |
|---|---|
| reintroduced the `CALL→BUY` fabrication fallback | `test_missing_trade_side_code_yields_unknown_not_a_guess` |
| asserted `possible_opening_transaction` at confidence 1.0 with "smart_money" wording | `test_no_intent_is_ever_asserted_with_certainty` + `test_forbidden_marketing_language_never_appears` |
| made `event_id` depend on a derived field (breaks replay) | `test_event_id_is_independent_of_derived_fields` |

## Test results

    pytest tests/test_flow_classifier.py -q     ->  50 passed
    pytest tests/test_architecture_canonical_imports.py -q -> 26 passed
    pytest -q                                   -> 271 passed, 0 failed

Verified live through the route on **real QuantData-shaped rows** run through the
real `flow_tape` normalizer: roll paired across expirations, spread legs paired,
hedge hypothesis raised on an OTM institutional put, MID → uncertain, zero-size
print → AMBIGUOUS/DEGRADED. `/api/flow_tape` unchanged; `/api/flow_classifier`
degrades to an honest `NOT_CONFIGURED` when the QuantData key is absent.

## Performance benchmarks

Pair detection was originally a full cross-scan (O(n²)) — the honest cost of
roll/spread hypotheses, which no single print can evidence. At realistic tape
sizes that was too slow for a polled endpoint, so prints are now indexed by
`(ticker, second)` and only the ±2s window is scanned. Semantics are identical
(all 50 tests unchanged; boundary tests added).

| rows | before | after | ms/row |
|---:|---:|---:|---:|
| 50 | 4.8 ms | **2.0 ms** | 0.041 |
| 200 | 51.4 ms | **6.6 ms** | 0.033 |
| 500 | 313.2 ms | **16.9 ms** | 0.034 |
| 1000 | 1171.1 ms | **34.9 ms** | 0.035 |
| 2000 | 4549.1 ms | **70.9 ms** | 0.035 |
| 5000 | — | **222.5 ms** | 0.044 |

~64× faster at 2000 rows; now linear.

## Migrations

**None.** No schema change — the classifier is stateless and derives from the
live tape on each request. (Step 3 clustering and Step 4 P/L will need
persistence; the `ALTER TABLE` migration pattern from 7.6 applies then.)

## Feature flags

| Flag | Default | Effect |
|---|---|---|
| `FLOW_CLASSIFIER_ENABLED` | `true` | off → route returns `available:false` with a note; nothing else changes |
| `FLOW_INSTITUTIONAL_PREMIUM` | `250000` | institutional-size threshold |
| `FLOW_RETAIL_PREMIUM` | `25000` | retail/noise threshold |
| `FLOW_PAIR_WINDOW_S` | `2` | roll/spread pairing window |
| `FLOW_DELAYED_PRINT_S` | `120` | print age before DELAYED warning |

Thresholds are exposed on `/api/flow_classifier/health` so a config change is
visible rather than silent.

## Rollback

1. Set `FLOW_CLASSIFIER_ENABLED=false` — instant, no deploy (route returns
   `available:false`; nothing else is affected).
2. Full: delete `engine/flow_classifier.py`, `engine/flow_classifier_routes.py`,
   `tests/test_flow_classifier.py`; revert the `app.py` import guard +
   registration block + `VERSION`. No schema or data to unwind.

The import guard is non-fatal, so even a broken module only prints a warning and
leaves the rest of APEX running.

## Known limitations

1. **Opening/closing intent is permanently unavailable** without open interest on
   the print. Enriching from the options chain (`engine/options/options_data_bus.py`
   has OI) is possible but adds a fetch per contract — deliberately not done here.
2. **Roll detection is heuristic.** Same right + different expiration + opposing
   aggression within 2s is *consistent with* a roll; the feed provides no leg
   linkage or account identity, so two unrelated traders can look like one roll.
   Emitted at 0.55 confidence with "cannot be proven to share an owner" in the basis.
3. **Hedge detection is weak by nature** (0.20–0.30). A protective put and a
   bearish put are identical on the tape; only the buyer's book distinguishes
   them, and it is not observable. The hypothesis is always offered *alongside*
   the directional one, never instead of it.
4. **Second-resolution timestamps.** The provider gives `HH:MM:SS` with no date
   and no sub-second sequence, so pairing is within-session and true event
   ordering inside a second is not recoverable. This will constrain Step 3's
   "out-of-order events" handling.
5. **`SINGLE_LEG` is a mild inference** — the provider may simply not have tagged
   a consolidation type. Confidence is 0.55, not 0.95, to reflect that.
6. **No UI surface yet.** Endpoint only, matching the approved sequence.
7. The upstream `_classify_row` fabrication (above) still affects
   `/api/flow_tape`'s own `aggressor_side` field — untouched by design.

## Next dependency

**Step 3 — Flow Clustering.** Unblocked: classifier tests pass. Clustering will
consume `classify_flow_events(...)["events"]` (classified events, never raw
provider rows, per spec), keyed on the deterministic `event_id` for auditable
membership. Note limitation 4 — second-resolution timestamps — when implementing
out-of-order and late-arriving print handling.
