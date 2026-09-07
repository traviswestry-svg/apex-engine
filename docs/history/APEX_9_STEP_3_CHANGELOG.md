# APEX 9 — Step 3: Flow Clustering

**Status:** complete. Full suite **319 passed / 0 failed** (was 271). 48 new tests.
**Gate:** clustering tests pass → Step 4 (Theoretical Flow P/L) is unblocked.

---

## Architectural rationale

Clustering is a read-only consumer of **classified** events, per spec — never of
raw provider rows. The decoupling is stronger than required:
`engine/flow_clusters.py` imports only `hashlib` and `os`. It does not import the
classifier, the tape, or any provider; it consumes the classifier's **output
contract** (`event_id`, `observable_facts`, `directional_bias`, …). No provider
field names appear anywhere in the module. `flow_tape.py` and
`flow_classifier.py` have **zero** references to clustering; `/api/flow_tape` and
`/api/flow_classifier` keep their exact shapes.

Pipeline: existing tape → classifier → clusterer, wired in `app.py` behind the
same non-fatal import guard as `premium_strategy` and Step 2.

### What a cluster is — and is not

A cluster is a set of prints **consistent with** related activity. It is not proof
of a single actor: the feed carries no account identity, no order id, and no leg
linkage, so two unrelated traders hitting the same contract in the same second
are indistinguishable from one trader working an order. Every cluster therefore
carries `confidence` (how well-linked the prints are — **capped at 0.85, never
1.0**) and `intent_uncertainty` (how unclear the purpose is), and every cluster
warns in plain text that a shared originator cannot be proven.

### The anti-over-clustering rule

Spec: *"Do not force unrelated transactions into a cluster merely because they
occurred close together."* Time proximity **alone never clusters**. Prints must
also share ticker, option type, expiration, and directional interpretation, and
sit inside a strike band. Opposing calls/puts, opposing directions in the same
contract, and distant strikes all stay separate. Mutation-testing confirms this
rule is load-bearing: removing `directional_interpretation` from the cluster key
breaks **35 of 48 tests**.

---

## 🐛 A real bug found by realistic data (not by the unit tests)

The unit tests passed while the algorithm was wrong. Running the full pipeline on
realistic interleaved prints exposed it:

    10:31:02  CALL 6300  sweep   ┐
    10:31:06  CALL 6300  sweep   │ one campaign
    10:31:07  CALL 6900  split   ← unrelated, lands *between* them
    10:31:11  CALL 6300  sweep   │
    10:31:19  CALL 6310  sweep   ┘

Chaining was a single sequential pass over time, so the out-of-band 6900 print
**broke the chain and forced a restart**, tearing one campaign into two clusters
(`:02,:06` and `:11,:19`). The split was an artefact of arrival interleaving, not
of the market — and it would have silently under-reported campaign size and
premium, exactly the kind of error that looks plausible on a dashboard.

**Fix:** band by strike **first** (`_strike_bands`), then time-chain within each
band. Banding uses **complete linkage** — a strike joins only if the band's whole
span stays inside tolerance — which also prevents single-linkage drift, where
6300~6360~6420 would daisy-chain into one implausibly wide cluster. Both
behaviours are now pinned by regression tests
(`test_unrelated_strike_between_prints_does_not_split_the_campaign`,
`test_strike_banding_uses_complete_linkage_and_does_not_drift`).

Verified after the fix on the same data: the campaign holds as one 4-print
cluster (6300–6310, $1.82M, 10:31:02–10:31:19); the 11:05 burst separates on the
gap; the opposing call, the puts, and the 6900 print each stay out.

---

## Determinism (replay, recomputation, late/out-of-order prints)

Events are de-duplicated by `event_id` and sorted by `(time, event_id)` before
banding and chaining, so **clustering is independent of arrival order**.
Late-arriving and out-of-order prints yield the same clusters as in-order arrival.
Recomputation over the full set is the supported model — not incremental mutation.

`cluster_id = sha1(config_version + key + sorted(member_ids))`. Identity **is**
membership: a late print that changes the members produces a **new id**, visibly,
rather than silently redefining an existing cluster. `cluster_key` is exposed
separately as the stable grouping handle for tracking across recomputation
(Step 4 will need it).

`CLUSTER_CONFIG_VERSION` is a fingerprint of the tunables, stamped on every
cluster — so a config change reshapes ids **visibly** instead of silently.

## What this layer cannot compute (and never fakes)

The spec's cluster output requires weighted delta, weighted implied volatility,
and number of exchanges. Verified against the classified-event contract: the
provider supplies **none** of these per print (`implied_volatility` and
`exchange_count` are explicitly `None`; there is no delta field at all).

They are emitted as `None` with a stated reason in `unavailable_metrics`:

| Metric | Why it is not derived |
|---|---|
| `weighted_delta` | No delta on the print and no IV to derive one. Backing IV out of a single trade price at an unknown quote would be false precision. |
| `weighted_implied_volatility` | Provider supplies no per-print IV. |
| `number_of_exchanges` | Provider supplies no exchange field; a SWEEP is taken as provider-reported rather than counted across venues. |

Mutation-tested: fabricating a plausible `weighted_delta: 0.42` is caught.

## Files

**Added**
- `engine/flow_clusters.py` — the engine (deterministic, no I/O, never raises).
- `engine/flow_clusters_routes.py` — `/api/flow_clusters`, `/api/flow_clusters/health`.
- `tests/test_flow_clusters.py` — 48 tests.
- `APEX_9_STEP_3_CHANGELOG.md`

**Modified**
- `app.py` — non-fatal import guard, route registration with injected read-only
  providers, `VERSION` → `9.3.0_FLOW_CLUSTERS`.

**Deleted:** none. **Upstream modified:** none.

## Cluster output contract

Every required field is emitted: `cluster_id` · `member_event_ids` · `start_time` ·
`end_time` · `duration_seconds` · `ticker` · `option_type` · `expiration` ·
`strike_range` · `total_premium` · `total_contracts` ·
`weighted_average_execution_price` · `weighted_delta` (None + reason) ·
`weighted_implied_volatility` (None + reason) · `number_of_prints` ·
`number_of_exchanges` (None + reason) · `aggression_score` ·
`repeat_intensity_score` · `classification_summary` · `intent_uncertainty` ·
`confidence` · `warnings` · `cluster_version` — plus `cluster_key`,
`cluster_config_version`, `classifier_versions`, `distinct_contracts`,
`premium_concentration`, `data_quality_summary`.

**Auditability:** `member_event_ids` are the classifier's deterministic ids, so
every cluster resolves back to its exact prints. `test_no_print_is_ever_lost`
proves every input event appears in exactly one of `clusters`, `singletons`, or
`unclusterable` — nothing is silently discarded.

## Tests — every required case

| Required case | Test |
|---|---|
| repeated sweeps in the same contract | `test_repeated_sweeps_same_contract_form_one_cluster`, `test_cluster_totals_are_sums_of_members` |
| related strikes | `test_nearby_strikes_cluster_together`, `test_distant_strikes_do_not_cluster` |
| different expirations | `test_different_expirations_never_cluster` |
| opposing calls and puts | `test_calls_and_puts_never_cluster_together`, `test_opposing_direction_same_contract_does_not_cluster` |
| separate institutions that cannot be linked | `test_prints_far_apart_in_time_are_not_linked`, `test_different_tickers_never_cluster`, `test_every_cluster_states_it_cannot_prove_a_shared_originator`, `test_cluster_confidence_never_reaches_certainty` |
| duplicate provider messages | `test_duplicate_messages_are_dropped_and_reported`, `test_duplicate_note_absent_when_no_duplicates` |
| late-arriving prints | `test_late_arriving_print_joins_on_recomputation` |
| out-of-order events | `test_clustering_is_independent_of_input_order`, `test_out_of_order_print_does_not_corrupt_time_bounds` |
| cluster splitting | `test_gap_larger_than_window_splits_into_two_clusters`, `test_split_clusters_have_distinct_ids_and_no_shared_members` |
| cluster merging | `test_bridging_print_merges_two_chains_on_recomputation` |
| session-boundary handling | `test_cluster_never_spans_the_session_close`, `test_cluster_never_spans_the_open`, `test_prints_inside_one_session_still_cluster` |

Plus: deterministic replay, config versioning, classifier-version comparison,
auditability, unavailable-metric declarations, intent-uncertainty reporting, and
the forbidden-language guard.

### Mutation-tested

| Injected fault | Caught by |
|---|---|
| cluster on time proximity alone (drop direction from key) | **35 tests** |
| ignore the strike band | `test_distant_strikes_do_not_cluster` |
| order-dependent `cluster_id` (breaks replay) | `test_cluster_id_is_deterministic_for_same_membership` |
| fabricate `weighted_delta: 0.42` / `weighted_iv: 0.18` | `test_underivable_metrics_are_none_with_a_stated_reason` (both params) |

## Test results

    pytest tests/test_flow_clusters.py -q  ->  48 passed
    pytest -q                              -> 319 passed, 0 failed

## Performance benchmarks

End-to-end (classify + cluster), mixed tickers/strikes/expirations:

| rows | classify | cluster | total | clusters |
|---:|---:|---:|---:|---:|
| 50 | 1.7 ms | 1.9 ms | **3.6 ms** | 7 |
| 200 | 6.0 ms | 6.7 ms | **12.7 ms** | 58 |
| 500 | 14.2 ms | 17.5 ms | **31.7 ms** | 126 |
| 1000 | 28.9 ms | 33.5 ms | **62.4 ms** | 251 |
| 2000 | 56.6 ms | 75.2 ms | **131.8 ms** | 485 |
| 5000 | 174.5 ms | 173.9 ms | **348.3 ms** | 1173 |

Comfortable for a polled endpoint at realistic tape sizes. Strike banding is
O(b) per print against the bands in its key group (b is small in practice), so
cost stays near-linear.

## Migrations

**None.** Clustering is stateless — clusters are recomputed from the live tape on
each request, which is also what makes replay and recomputation exact. Step 4
(P/L) will need persistence to track marks over time; the 7.6 `ALTER TABLE`
pattern applies then, and `cluster_key` is the stable handle to persist against.

## Feature flags

| Flag | Default | Effect |
|---|---|---|
| `FLOW_CLUSTERING_ENABLED` | `true` | off → route returns `available:false`; nothing else changes |
| `FLOW_CLUSTER_GAP_S` | `120` | max seconds between prints in one chain |
| `FLOW_CLUSTER_STRIKE_BAND_PCT` | `0.01` | strike band width (1% ≈ 63 pts on SPX) |
| `FLOW_CLUSTER_MIN_PRINTS` | `2` | below this a cluster is reported as a singleton (never dropped) |
| `FLOW_CLUSTER_SESSION_BOUNDARIES` | `09:30,16:00` | clusters may not span these |

All are exposed on `/api/flow_clusters/health` and folded into
`CLUSTER_CONFIG_VERSION`, so a config change is visible in every `cluster_id`
rather than silently reshaping history.

## Rollback

1. `FLOW_CLUSTERING_ENABLED=false` — instant, no deploy.
2. Full: delete `engine/flow_clusters.py`, `engine/flow_clusters_routes.py`,
   `tests/test_flow_clusters.py`; revert the `app.py` guard + registration +
   `VERSION`. No schema or data to unwind.

## Known limitations

1. **Duplicate detection is a fingerprint, not an identity.** `event_id` hashes
   the print's identifying fields, so a genuinely distinct print with identical
   ticker/time/strike/price/size is **indistinguishable** from a duplicated
   message. We de-duplicate (under-counting a repeat beats inventing volume) and
   surface `identical_prints_collapsed` + a note. This is a feed limitation, not
   a fixable bug.
2. **Second-resolution timestamps** (flagged in Step 2). No date and no
   sub-second sequence, so ordering inside a second falls back to `event_id`, and
   session boundaries are inferred from time-of-day rather than a real session
   date. A multi-day fetch would need a date field to cluster safely.
3. **Cluster confidence is capped at 0.85** by construction. Without account
   identity, linkage is always inference; a cluster should never present as fact.
4. **Direction is part of the key**, so a genuine campaign that legs in on both
   sides (buying calls *and* selling calls) appears as two clusters. That is the
   conservative error: separating related activity is recoverable by eye, merging
   opposing activity would invent a phantom position.
5. **No UI surface yet** — endpoint only, per the approved sequence.
6. **`weighted_delta` / `weighted_iv` / `number_of_exchanges` are permanently
   unavailable** at this layer (above). Enriching from
   `engine/options/options_data_bus.py` is possible but is a per-contract fetch
   and an explicit, stamped decision — not something to slip in silently.

## Next dependency

**Step 4 — Theoretical Flow P/L.** Unblocked: clustering tests pass. It will
consume `build_flow_clusters(...)["clusters"]` plus member events, keyed on
`cluster_key` (stable across recomputation) rather than `cluster_id` (which
changes with membership by design).

Two constraints Step 4 inherits and must confront up front:
- **No quotes.** The spec's P/L methods (bid / ask / midpoint / conservative
  executable mark / theoretical value) all need a current quote. The flow feed
  has none — marks must come from the options chain
  (`engine/options/options_data_bus.py`), which is a per-contract fetch. That is
  a real design decision to settle before coding, not during.
- **Uncertain package construction.** The spec explicitly requires that an
  uncertain spread or roll is not treated as a naked directional position.
  `intent_uncertainty` and the `spread_leg_candidate` / `likely_roll` counts are
  already on every cluster to drive exactly that warning.
