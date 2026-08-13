# APEX 9 — Step 5a: Point-in-time feature store + leakage guards

**Status:** complete. Full suite **476 passed / 0 failed** (was 388). 88 new tests.
**Scope:** the store and its refusals only. **No similarity engine** — that is 5b, and it
should not be built until this has real sessions underneath it.

---

## Design principle: refuse, don't warn

A leaky feature store does not crash. It produces a confident, well-tested,
entirely fictional edge — a backtest reporting 71% on a signal that knew the
answer. Everything downstream looks healthy, which is exactly what makes it
expensive.

So every guard here **raises `LeakageError` and refuses to produce the vector**.
There is no `force=`, no `strict=False`, no warning path. A feature vector that
cannot be *proven* non-leaking is not produced. Defaults are paranoid: unknown
feature name → refused; missing availability timestamp → refused; ambiguous
revision status → refused.

## The two-record rule, made physical

`flow_features` and `flow_labels` are **separate tables** sharing only
`sample_id`. This is not tidiness — it is the rule enforced in the schema. There
is deliberately:

- no SQL view joining them (verified: 0 views),
- no endpoint serving them joined,
- no convenience reader returning a flat row containing a feature and an outcome.

The only join returning label *values* is `load_training_pairs()`, which enforces
the session split **before reading a row**. (`unlabelled_samples()` also joins,
but returns `sample_id`s only — no label values.) Even that returns features and
labels in **named sub-objects**, so a caller cannot sweep a label into a feature
matrix with `list(row.values())`.

## The timing rule

Every feature is a `Feature(name, value, available_at, source, revised, revision_of)`.
A raw dict is refused — anything without an availability stamp cannot be proven
non-leaking. Admissibility is strict:

    available_at <= decision_time

A replay frame stamped 10:31:05 cannot inform a decision at 10:31:02, even by
three seconds. The boundary is inclusive at equality (knowable *at* the decision
is knowable). Per-field lag is recorded, and `max_feature_lag_seconds` lands on
every vector — so a 5-minute-stale frame is visible, not silent.

### `resolve_frame_at_or_before` — the join *is* the boundary

Named for what it does. "Nearest frame" is the classic leak: a frame 3 seconds
*after* a decision is nearer than one 5 minutes before, and using it hands the
model the future. This resolver only ever looks backwards, with an optional
`max_staleness_seconds`.

## Files

**Added**
- `engine/feature_store.py` — `Feature`, `LeakageError`, admissibility,
  vector/label builders, frame resolution, session-split guards, sample-quality
  tiers, Wilson intervals. Pure; no I/O.
- `engine/feature_store_db.py` — the two tables, immutability, the sanctioned join.
- `engine/feature_store_routes.py` — `/api/feature_store/health` (health only).
- `tests/test_feature_store.py` — 88 tests.
- `APEX_9_STEP_5A_CHANGELOG.md`

**Modified**
- `app.py` — non-fatal import guard + registration, `VERSION` → `9.5.0_FEATURE_STORE`.

**Deleted:** none. **Upstream modified:** none. The store imports no provider, no
tape, no classifier — it is pure functions plus its own tables.

## Leakage controls — one test per spec-named control, all refusing

| Spec control | Enforced by | Tests |
|---|---|---|
| MFE/MAE in live features | `FORBIDDEN_FEATURE_NAMES` + substring guard (catches `cluster_mfe_dollars`) | 7 |
| final outcome in pre-trade inputs | same | 8 |
| EOD open interest used intraday | name guard **and**, independently, the timing rule (refused even if renamed) | 2 |
| revised data treated as contemporaneous | `revised=True` requires `revision_of`; a revision that predates what it revises is refused | 3 |
| future GEX snapshots | timing rule (+ `future_` substring) | 2 |
| future volume-profile states | timing rule (+ `next_` substring) | 2 |
| session-closing labels before close | `FORBIDDEN` names + `settled_at < decision_time` refused | 6 |
| train/eval overlap | `assert_disjoint_sessions` + `assert_chronological_split` | 4 |

Two guards beyond the spec:

- **`samples` is refused as a feature.** Step 4.1 limitation 4: it counts how
  often something was *observed*, not market activity. It would look predictive
  and be an artefact of polling.
- **Chronological split enforced, not just disjoint.** A random split across
  sessions leaks regime knowledge backwards — learning from Thursday to predict
  Tuesday, which no live system can do. The spec only asked for non-overlap.

### Mutation-tested — every guard is load-bearing

| Injected fault | Tests caught |
|---|---|
| allow features that postdate the decision (**the core leak**) | 4 |
| drop the forbidden-name check | **25** |
| allow revised data with no `revision_of` (EOD smuggling) | 2 |
| resolver picks *nearest* frame instead of at-or-before | 2 |
| allow train/eval overlap | 2 |
| allow non-chronological split | 2 |
| features become mutable (history rewritten) | 1 |
| `sample_quality` permits edge claims at any n | 4 |

## Immutability

`write_features` **refuses to overwrite** an existing sample. A flow cluster
mutates as late prints arrive (Step 3, by design), so re-deriving features later
would rewrite history with knowledge the original decision never had. Labels *are*
updatable — that is what a label is, and excursions widen over the session.

## Two exclusion reasons, deliberately not conflated

A correction found during end-to-end verification: a code comment claimed
`features_from_frame` dropped coach/story fields. It did not — the test passed
only because `mfe_dollars`/`final_outcome` trip the forbidden guard. Fixing it
properly required separating two different reasons:

- **`FORBIDDEN_FEATURE_NAMES`** — outcome data. A **leak**.
- **`NON_FEATURE_FIELDS`** — `executive_summary`, `coach_entry/stop/t1/t2`. **Not
  a leak** (the story engine describes state as of the frame, so they were
  genuinely available) — they are prose and per-trade price levels, excluded on
  **modelling** grounds: unusable in a distance metric, effectively unique per
  sample.

A test asserts the two sets are disjoint, so the reasons cannot blur.

**APEX's own state is deliberately kept**: `ici`, `grade`, `decision_state`,
`recommendation`, `coach_action`, `approved_side`. Those were knowable at the
decision, and conditioning on them is the *point* — it is how you learn whether
APEX's own calls fare better in some regimes than others.

Verified on the real `replay_snapshots` shape: **20 features kept**, prose and
price levels excluded, APEX state retained, and the 10:36 frame refused for a
10:31 decision.

## Sample-size honesty — a gap in the spec, closed

The spec's thresholds (<20 insufficient · 20–49 exploratory · 50–199 moderate ·
200+ stronger) never say **global or per-neighbourhood**. Applied globally they
would bless "stronger evidence" at 200 total rows while the matched cell holds
three. That is a leak that is not on the spec's leakage list, and it is the one
most likely to ship a fictional edge.

`sample_quality(n)` is therefore documented and named for the **matched
neighbourhood** count, states that in its own output (`basis`), exposes
`edge_claim_permitted` (false below 50), and — at the 200+ tier — still warns
that correlated days are not independent observations.

`wilson_interval()` is provided so 5b reports intervals rather than raw win
rates. Wilson over the normal approximation because it stays sane at small n and
near 0/1 — exactly where a thin neighbourhood lives.

`/api/feature_store/health` reports the **global** count and says plainly that
similarity must grade on the matched count, never on that total.

## Test results

    pytest tests/test_feature_store.py -q  ->  88 passed
    pytest -q                              -> 476 passed, 0 failed
    architecture guard                     ->  26 passed

## Migrations

Two new tables, `CREATE TABLE IF NOT EXISTS` at registration, in the existing
`DB_PATH`. Verified coexisting with `apex_signals`, `pine_signals`,
`premium_recommendations`, `flow_pl_tracking`, `replay_snapshots`, etc. Init
failure is non-fatal.

## Feature flags

None yet — the store is inert until 5b writes to it. `/api/feature_store/health`
is read-only diagnostics.

## Rollback

Delete the three `feature_store*` modules and the test file; revert the `app.py`
guard + registration + `VERSION`. Schema: `DROP TABLE flow_features;
DROP TABLE flow_labels;` — nothing else references them.

## Known limitations

1. **Nothing populates the store yet.** 5b must build samples at cluster close
   and labels at settle. Deliberate: the guards are proven first, on synthetic
   data, where every leak can be constructed on purpose.
2. **Frame cadence is irregular.** Replay frames land every ~300s headless, but
   denser when a dashboard polls — so `max_feature_lag_seconds` varies with
   attention. It is recorded per sample rather than assumed away; 5b should
   consider a `max_staleness_seconds` cut so thinly-observed decisions don't
   silently carry stale features.
3. **`replay_snapshots` still has no pruning.** `REPLAY_MAX_FRAMES=480` caps
   memory only; the table grows unbounded. Not addressed here — it is a separate
   change to an existing subsystem.
4. **The forbidden-substring net will produce false positives.** Any legitimate
   feature containing `close`, `next_`, `final_` etc. is refused until added to
   `SUBSTRING_ALLOWLIST` with a written justification. That friction is the
   intent: the allowlist is small and every entry is a hole in the net.
5. **No backfill is possible.** As established: `flow_bias`, `ici`,
   `decision_state` and the clusters themselves derive from a live QuantData
   snapshot with no history endpoint. Samples accrue forward only, at wall-clock
   speed.

## Next dependency

**Step 5b — similarity engine.** Blocked on **data, not code**:

- Wire sample writing (features at cluster close, labels at settle) — small, and
  the guards already exist to make it safe.
- Then let it accumulate. Global counts arrive in days; **matched-neighbourhood
  counts take months** (~1.4 samples/cell/day across a modest 72-cell regime
  slice ≈ ~7 months to 200 in one cell), and correlated days are not independent
  observations.

Until then 5b should ship read-only: nearest samples, matched counts, and Wilson
intervals surfaced — with `edge_claim_permitted=false` suppressing any rate
presented as a finding.
