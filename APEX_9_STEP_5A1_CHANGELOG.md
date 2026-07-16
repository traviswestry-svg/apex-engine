# APEX 9 — Step 5a.1: Feature store writer (the clock starts)

**Status:** complete. Full suite **512 passed / 0 failed** (was 476). 36 new tests.
**Effect:** `flow_features` now accumulates. Before this, it was inert — 0 rows today, 0 rows in six months.

---

## The decision point — the question that had to be settled first

A cluster mutates as prints arrive, so "now" is not a decision point. Two rules
resolve it:

- **`decision_time` = the cluster's `end_time`** (its last print) — the instant
  the campaign was observable in full.
- **The sample is written only once the cluster is SEALED**:
  `now >= end_time + FLOW_CLUSTER_GAP_S`. Past that, Step 3's gap rule means no
  later print can chain to it, so membership can no longer grow.

**Writing at seal while stamping `decision_time = end_time` is the crux.**
Features are resolved at-or-before `end_time`, so the ~2 minutes spent waiting for
the seal buys completeness **without leaking hindsight**. Mutating that stamp to
write-time breaks 3 tests.

### Why first-write-wins is correct here

The tape is a sliding window (last ~100 prints). A cluster is visible only while
its prints remain in it; as the window slides members age out and the cluster
**shrinks**. So the first sealed observation is the most complete one that will
ever exist — immutability isn't just a safety rule here, it captures the best
snapshot. Pinned by `test_shrunken_cluster_cannot_overwrite_the_fuller_first_sample`.

## The label — and whose target it is

Outcomes are measured to **session close**. `target_hit` / `stop_hit` use
**APEX-defined thresholds on the cluster's own cost basis** (default +100% / −50%,
both flags). We do not know the participant's real targets and pretending to would
be fabrication — the label record says so in its own `label_basis`.

**Ordering matters more than either flag.** A cluster that hit −50% *before* +100%
was a loser, not a winner. `final_outcome` compares `time_to_mae` with
`time_to_mfe`:

    TARGET_FIRST · STOP_FIRST · TARGET_ONLY · STOP_ONLY · NEITHER
    BOTH_SAME_SAMPLE      — both landed in one 300s interval; true order is not
                            observable, so it is reported, not guessed
    BOTH_ORDER_UNKNOWN    — excursion times unavailable

Mutating "target wins whenever both hit" breaks a test. So does guessing an order
for `BOTH_SAME_SAMPLE`.

## 🐛 Cluster labels were measured on the wrong thing

`flow_pl_tracking` records excursions **per event**. But a Step 5 sample **is a
cluster** — and member MFEs cannot be summed into a cluster MFE, because members
do not peak simultaneously. A sum reports a peak the cluster never reached, which
would have inflated every label in the store.

Fixed properly rather than approximated: new table `flow_pl_cluster_tracking`
records the **cluster's own aggregate P/L** in its own MFE/MAE envelope, written
by the shared pipeline so both the endpoint and the scanner feed it.

## 🐛 The writer silently wrote zero samples

Found only by running the real scanner path end-to-end: **every unit test passed
while the writer produced nothing.**

`compute_cluster_pl` returns a **P/L view** — it drops Step 3's descriptive fields
(`end_time`, `aggression_score`, `number_of_prints`…). The writer needs the
**cluster view**, so `end_time` was `None` and every cluster was refused. The
report said `refused: 1`; nothing crashed.

Fixed by a clean separation rather than by widening the P/L payload: the pipeline
now returns `source_clusters` (Step 3 view) alongside `clusters` (P/L view). The
writer consumes clusters; labels come from cluster tracking, which already holds
cost basis — so the writer never needs the P/L view at all. Pinned by 5 regression
tests, including `test_pl_view_deliberately_stays_a_pl_view`.

## 🐛 A real production bug, surfaced by the clock moving mid-session

`tests/test_premium_strategy.py::test_grade_scratches_no_trade_and_holds_missing_bars`
passed at 09:59 and failed at 22:11 **with no code change between**. Not flaky —
latent:

```python
# No bars yet — retry later, unless the session is > 2 days stale.
if rec_utc < _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=2):
```

`grade_due_recommendations` **takes an injected clock** (`now_et_provider`) and
resolves it as `now_et` — then this line ignored it and read the wall clock. The
test's record was dated 2026-07-14; two days of real time elapsed during this
session and the staleness rule fired regardless of the clock the caller supplied.

**Fixed at source** (not worked around in the test): the check now uses `now_et`.
The rule is deterministic and replayable again, matching the rest of the function.
Regression test asserts both sides — fresh clock → retry, advanced clock → scratch
— so it can never rot back into wall-clock dependence.

This is the same class as the two date-dependent `test_decision_intelligence`
tests flagged in the Step 1 changelog. Those remain outstanding.

## Files

**Added**
- `engine/feature_store_writer.py` — sealing rule, sample writing, label settling.
- `tests/test_feature_store_writer.py` — 30 tests.
- `APEX_9_STEP_5A1_CHANGELOG.md`

**Modified**
- `engine/flow_pl_store.py` — `flow_pl_cluster_tracking` table,
  `record_cluster_observation`, `get_cluster_excursions`.
- `engine/flow_pl_pipeline.py` — records cluster observations; returns `source_clusters`.
- `engine/premium_strategy_routes.py` — **the injected-clock fix**.
- `app.py` — writer guard + flags, scanner hooks, `VERSION` → `9.5.1_FEATURE_STORE_WRITER`.
- `tests/test_flow_pl.py` (+6), `tests/test_premium_strategy.py` (+1).

## Scanner integration — one pipeline run feeds both

The P/L sampler already prices clusters every cycle. Running the pipeline again
for the writer would **double the chain calls**, so the scanner makes **one**
`run_flow_pl` call and feeds both:

    run_flow_pl(...)  →  P/L samples (flow_pl_tracking + flow_pl_cluster_tracking)
                      →  source_clusters  →  feature_store_writer.write_samples()

Label settling runs only in `AFTER_HOURS`/`OVERNIGHT` (labels are measured *to*
the close, so settling before it would be a leak), once per session date, guarded
by `_LAST_LABEL_SETTLE_DATE`. Verified: 6/6 hook guards present.

**No added API cost** over Step 4.1 — same single pipeline run.

## Tests

| Concern | Tests |
|---|---|
| sealing rule (unsealed skipped, boundary, sealed written) | 3 |
| decision_time is cluster end, not write time | 1 |
| features come from the frame *before* the decision | 1 |
| idempotence + shrunken cluster can't overwrite | 2 |
| no frame / stale frame → skip with a reason | 2 |
| cluster features whitelisted & prefixed; prose excluded | 2 |
| outcome ordering (target/stop/neither/first/same-sample/unknown) | 7 |
| labelling from cluster excursions, basis text, idempotence | 5 |
| cluster excursion envelope, session scoping | 3 |
| `source_clusters` regression | 5 |
| injected-clock regression | 1 |

### Mutation-tested

| Injected fault | Caught |
|---|---|
| write immediately, no seal | 2 |
| stamp decision_time as write time (leaks hindsight) | 3 |
| resolve the *nearest* frame (may be future) | **14** |
| target wins whenever both hit (ignore ordering) | 1 |
| guess an order when both land in one sample | 1 |
| accept any cluster field as a feature (no whitelist) | 1 |

## Migrations

New table `flow_pl_cluster_tracking` (cluster_key + session_date PK), created at
init alongside `flow_pl_tracking`. Non-fatal.

## Feature flags

| Flag | Default | Effect |
|---|---|---|
| `WRITE_FEATURES_IN_SCANNER` | `true` | off → no sample/label writing; everything else unaffected |
| `FEATURE_WRITE_SESSIONS` | `MARKET_OPEN` | sessions in which samples are written |
| `FEATURE_MAX_FRAME_STALENESS_S` | `600` | beyond this, skip rather than write stale features |
| `FLOW_LABEL_TARGET_PCT` | `100` | target threshold, % of cost basis |
| `FLOW_LABEL_STOP_PCT` | `-50` | stop threshold, % of cost basis |

## Rollback

`WRITE_FEATURES_IN_SCANNER=false` — instant. Full: delete
`feature_store_writer.py` + its tests, revert the pipeline's `source_clusters` and
cluster-observation lines, the `flow_pl_store` additions, and the `app.py` hooks.
`DROP TABLE flow_pl_cluster_tracking;` — nothing else reads it.

**Keep the `premium_strategy_routes.py` clock fix regardless** — it is an
independent correctness fix and reverting it re-introduces a real bug.

## Known limitations

1. **Sealing costs ~2 minutes of latency** per sample. Correct, not free: a
   cluster is written at `end_time + 120s`. If the scan interval (300s) skips past
   the window while the tape slides, a short-lived cluster can age out before it is
   ever seen sealed. **Expect some sample loss on busy tapes** — the writer reports
   it, but does not currently count it (it cannot see what it never observed).
2. **Only `ASSISTANT_TICKER` is sampled**, inherited from Step 4.1.
3. **Target/stop thresholds are arbitrary.** +100%/−50% are conventional 0DTE
   figures, not derived from your trading. They are baked into labels that cannot
   be recomputed later, so change them **before** accumulating history you care
   about, not after.
4. **`BOTH_SAME_SAMPLE` will be common on fast movers** at a 300s grid. Step 5b
   must treat it as a distinct outcome class, not fold it into wins or losses.
5. **`replay_snapshots` still has no pruning** (carried from 5a).
6. Frame staleness varies with dashboard attention; `max_feature_lag_seconds` is
   recorded per sample so 5b can filter on it.

## Next dependency

**Step 5b — similarity engine.** Now genuinely blocked on **calendar time only**.
The clock is running: deploy and let it accumulate. Global counts arrive in days;
matched-neighbourhood counts take months.

Before 5b, worth reviewing after a few live sessions:
- the real rate of `BOTH_SAME_SAMPLE` and `no_excursion`;
- how many clusters age out unsealed (limitation 1);
- whether +100%/−50% match how you actually trade these (limitation 3) — this is
  the one decision that is expensive to change later.
