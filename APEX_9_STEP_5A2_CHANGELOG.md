# APEX 9 — Step 5a.2: Feature store records API

**Status:** complete. Full suite **537 passed / 0 failed** (was 512). 25 new tests.
**Adds:** `/samples`, `/sample/<id>`, `/coverage`. **Deliberately omits:** any flat feature+label export.

---

## The distinction that shaped this

A human reading one record is **not** the leak. The leak is a **bulk flat export**
fed to a trainer. So inspection can be generous, provided:

- features and labels are never merged into one object;
- bulk training reads still go through `load_training_pairs()`, in-process, with
  its enforced train/eval split.

## Endpoints

| Route | Returns |
|---|---|
| `GET /api/feature_store/samples?session=&limit=&offset=` | Pre-decision vectors **only**. Labels are not read by this route at all. Includes `feature_availability` per field (source, `available_at`, `lag_seconds`) and `max_feature_lag_seconds`. |
| `GET /api/feature_store/sample/<sample_id>` | One record: `pre_decision{features, feature_availability}` and `post_outcome{labels, label_basis}` as **separate named objects**. `post_outcome` is `null` until settled — the normal state mid-session. |
| `GET /api/feature_store/coverage?dims=&sessions=` | **Matched-neighbourhood counts.** The number that actually gates 5b. |
| `GET /api/feature_store/health` | Now also carries `writer{}` settings and points at `/coverage` as the real gate. |

### What is deliberately absent

No `/api/feature_store/training_data`, `/pairs`, `/export`, or `/rows`. Such an
endpoint would make the split enforcement **bypassable with a URL**. A test
asserts all four 404.

Verified: the routes reach only `get_sample`, `list_features`,
`neighbourhood_coverage`, `sessions`, `health`. No flat pair reader is reachable
over HTTP.

## `/coverage` — why it's the one that matters

It answers the only question that gates 5b: *not* "how many rows do I have" but
"how many do I have **in cells that resemble each other**".

Buckets by `gamma_regime × auction_state × cluster_directional_interpretation ×
premium_band` (overridable via `?dims=`), grades each cell with
`sample_quality()`, and exposes `edge_claim_permitted` per cell.

**Premium bands reuse the classifier's own thresholds** (`_INSTITUTIONAL_PREMIUM`,
`_RETAIL_PREMIUM`) rather than inventing parallel ones that could drift.

**Aggregation happens in the data layer.** `neighbourhood_coverage()` joins
internally and returns per-cell aggregates — no caller ever holds a flat
feature+label row, so the diagnostic cannot become a training path.

### Rates are withheld on thin cells

Counts are always shown. **Rates are reported only where
`edge_claim_permitted`** — otherwise `target_first_rate` is `null` with
`rate_withheld_because`. A 3-sample cell *has* a win rate; printing it is how a
fictional edge gets believed. When permitted, the rate is a **Wilson interval**,
never a bare point estimate.

`TARGET_FIRST` and `TARGET_ONLY` count as hits; `STOP_FIRST` does **not** — a
cluster that stopped out before reaching target was a loser. Mutating that to
count all labelled samples as hits breaks 2 tests.

### The demonstration that justifies the whole design

Simulated 15 sessions × ~100 clusters (1,500 samples):

    GLOBAL:  1500 samples, 15 sessions -> tier 'stronger', edge claims TRUE
    MATCHED: 72 cells, cells permitting edge claims: 0/72
             largest cell n=31 ('exploratory')
    72 of 72 cells still withhold their rate after 15 sessions

The global counter says **"stronger evidence, proceed"** while **every actual
neighbourhood says "exploratory, withhold"**. That is precisely the spec gap
flagged in 5a, now visible as an endpoint rather than an argument.

## Files

**Modified**
- `engine/feature_store_db.py` — `list_features`, `get_label`, `get_sample`,
  `neighbourhood_coverage`, `_premium_band`.
- `engine/feature_store_routes.py` — three new routes; health now includes writer settings.

**Added**
- `tests/test_feature_store_api.py` — 25 tests.
- `APEX_9_STEP_5A2_CHANGELOG.md`

**Deleted:** none. **Upstream modified:** none. No `app.py` change — the routes
register through the existing guard.

## Tests

| Concern | Tests |
|---|---|
| `/samples` returns features, **never** labels | 3 |
| availability stamps carried; session filter; limit clamped; garbage params; empty store | 4 |
| `/sample/<id>` keeps halves apart; null outcome pre-settle; unknown id | 4 |
| `/coverage` bucketing, custom dims, session filter, empty store | 4 |
| premium bands reuse classifier thresholds | 1 |
| **rate withheld on thin cell, counts still shown** | 1 |
| rate + Wilson interval once permitted | 1 |
| STOP_FIRST not counted as a hit | 1 |
| unlabelled counted, outcomes not | 1 |
| basis states per-neighbourhood + non-independence | 1 |
| **flat export endpoints 404** | 1 |
| health points at coverage; exposes writer caveats | 2 |

### Mutation-tested

| Injected fault | Caught |
|---|---|
| print the rate regardless of sample count | 1 |
| count `STOP_FIRST` as a target hit | 2 |
| `/samples` leaks labels | 2 |
| merge `pre_decision` and `post_outcome` into one flat dict | 1 |

A note on test quality: the first run failed because my own fixture generated
`10:30:61` as a timestamp. The store **refused it** as unparseable. The guard was
right and the test data was wrong — which is the correct direction for that
argument to go.

## Migrations / flags

None. Read-only routes over the existing tables.

## Rollback

Revert `feature_store_routes.py` to the health-only version and drop the new
reader functions from `feature_store_db.py`. Nothing else depends on them.

## Known limitations

1. **`/coverage` scans all feature rows in Python**, not SQL. Fine at the
   thousands-of-rows scale this store will occupy for months; if it ever reaches
   six figures, push the bucketing into SQL via `json_extract`.
2. **Cells are exact-match, not nearest-neighbour.** Coverage answers "how many
   samples share these exact regime labels" — 5b's similarity will be softer
   (distance-weighted), so its effective matched count may differ. Coverage is
   the conservative floor.
3. **`premium_band` is the only derived dim.** Others (moneyness bands, DTE
   buckets) would need adding to `_DERIVED_DIMS` deliberately.
4. **No pagination on `/coverage`** — bounded by cell count, not row count, so it
   stays small by construction.

## Next dependency

**Step 5b — similarity engine.** Unchanged: blocked on calendar time. `/coverage`
now makes the wait measurable rather than estimated — check it after a few live
sessions and watch `cells_permitting_edge_claims` rather than the global total.
