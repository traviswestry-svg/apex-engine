# APEX 9 — Step 4.1: Scanner-side Flow P/L sampling

**Status:** complete. Full suite **388 passed / 0 failed** (was 374). 14 new tests.
**Closes:** Step 4's known limitation #1 — the one that would have contaminated Step 5.

---

## Why this existed as a gap

Step 4 shipped with MFE/MAE accumulating **only while `/api/flow_pl` was being
polled**. That meant excursions described *the polling pattern*, not the session:
a print that ripped +$400k while nobody had the dashboard open recorded no
excursion at all, and one watched closely for ten minutes looked far more
eventful than one watched for ten seconds.

That is not a cosmetic gap. Step 5 builds its **labels** from exactly this data.
Training a similarity engine on excursions shaped by when a human happened to
have a browser tab open would produce confident, well-tested, entirely fictional
edge estimates — the single most expensive failure mode in the whole APEX 9 plan.

## Architectural decision: one pipeline, two callers

The sampler needs the identical sequence the endpoint runs:

    tape → classify → cluster → enrich from chain → price → record

Implementing that twice is exactly the drift `ARCHITECTURE.md` warns about — the
route and the sampler would slowly disagree about what a mark means, the recorded
history would stop matching the numbers on screen, and **no test could see it**
because each side would pass its own.

So the pipeline was **extracted** into `engine/flow_pl_pipeline.py` and both
callers became thin wrappers:

| | before | after |
|---|---|---|
| `flow_pl_routes.py` | 200 lines, owned the pipeline + `_ChainCache` | **94 lines**, zero pricing logic, delegates to `run_flow_pl` |
| scanner sampler | would have been a second copy | `sample_flow_pl(**args)` — same function |

Verified: `compute_event_pl` is called **0 times** in routes, `_ChainCache` no
longer exists there, and `test_sampler_and_endpoint_share_one_pipeline` asserts
identical marks, P/L and cluster ids from both paths.

This is a refactor of Step 4 code, not new duplicate machinery — the net line
count barely moved.

## Files

**Added**
- `engine/flow_pl_pipeline.py` — the single pipeline (`run_flow_pl`,
  `sample_flow_pl`, `ChainCache`). Read-only; all data paths injected; never raises.

**Modified**
- `engine/flow_pl_routes.py` — rewritten as a thin wrapper (200 → 94 lines).
- `app.py` — sampler import guard, `SAMPLE_FLOW_PL_IN_SCANNER` +
  `FLOW_PL_SAMPLE_SESSIONS`, scanner-cycle hook, `_FLOW_PL_SAMPLE_ARGS`
  published from the registration block, `VERSION` → `9.4.1_FLOW_PL_SAMPLER`.
- `tests/test_flow_pl.py` — +14 tests.

**Deleted:** none. **Upstream modified:** none.

## The scanner hook

Mirrors the 7.6 premium-grading pattern exactly — guarded, session-gated,
non-fatal, reports a count:

```python
if (SAMPLE_FLOW_PL_IN_SCANNER and FLOW_PL_SAMPLER_AVAILABLE
        and _flow_pl_sample is not None and globals().get("_FLOW_PL_SAMPLE_ARGS")):
    try:
        if session_status() in FLOW_PL_SAMPLE_SESSIONS:
            _fs = _flow_pl_sample(**globals()["_FLOW_PL_SAMPLE_ARGS"])
            if _fs:
                print(f"flow_pl: sampled {_fs} print(s).", flush=True)
    except Exception as e:
        print(f"flow P/L sample error (recovered): {e}", flush=True)
```

`_FLOW_PL_SAMPLE_ARGS` is published from the registration block rather than
resolved at import, because the closures depend on the chain fetcher wired for
the Trade Command Center further down `app.py`. The `globals().get(...)` guard
means a failed wiring degrades to *no sampling*, never to a `NameError` in the
scanner thread.

The sampler passes `attach_excursions=False`: it **writes** history, it does not
need to read it back, and skipping the read keeps the cycle cheap.

## API cost (the real trade-off)

Per sampled cycle: **1 flow-tape fetch + N chain fetches**, where N is distinct
`(ticker, expiration, side)` groups — not print count, because `get_chain`
returns a whole chain and it is cached per run.

Typical SPX 0DTE: 1 tape + 2 chain (CALL/PUT) = **3 calls per 300s cycle**
≈ 36/hour. Gated to `MARKET_OPEN` (~6.5h) ≈ **~234 additional calls/day**.

Gating is why `FLOW_PL_SAMPLE_SESSIONS` defaults to `MARKET_OPEN` alone:
sampling overnight would burn chain calls marking contracts whose quotes are not
moving, for excursions no one will trade on.

## Tests

| Concern | Test |
|---|---|
| **history accrues with nobody watching** (the whole point) | `test_sampler_records_history_with_nobody_watching` |
| repeated cycles widen MFE/MAE | `test_repeated_sampling_widens_the_excursion_envelope` |
| **route and sampler cannot drift** | `test_sampler_and_endpoint_share_one_pipeline` |
| sampler skips read-back, endpoint doesn't | `test_sampler_skips_excursion_readback_endpoint_does_not` |
| nothing markable → 0 samples | `test_sampler_returns_zero_when_nothing_markable` |
| empty tape → 0 | `test_sampler_returns_zero_on_empty_tape` |
| broken tape provider never raises | `test_sampler_never_raises_on_a_broken_tape_provider` |
| broken chain fetcher never raises | `test_sampler_never_raises_on_a_broken_chain_fetcher` |
| chain failure surfaces as a warning | `test_pipeline_reports_chain_warning_when_fetch_fails` |
| no chain fetcher at all → unmarkable, not zero | `test_sampler_works_with_no_chain_fetcher_at_all` |
| `track=False` records nothing | `test_tracking_off_records_nothing` |
| **one fetch per expiration+side** | `test_chain_cache_fetches_once_per_expiration_and_side` (3 prints → 2 fetches) |
| fetch count reported | `test_chain_cache_counts_fetches_in_payload` |
| sample count reported | `test_samples_recorded_is_reported` |

    pytest tests/test_flow_pl.py -q  ->  69 passed
    pytest -q                        -> 388 passed, 0 failed

**Verified live through app.py's real wiring:** sampler available, sampling
enabled, gated to `MARKET_OPEN`, args published with the chain fetcher wired;
two simulated cycles → 2 events / 4 samples in `flow_pl_tracking`, with no
dashboard open.

## Migrations

**None** — reuses Step 4's `flow_pl_tracking` table unchanged.

## Feature flags

| Flag | Default | Effect |
|---|---|---|
| `SAMPLE_FLOW_PL_IN_SCANNER` | `true` | off → no scanner sampling; endpoint unaffected |
| `FLOW_PL_SAMPLE_SESSIONS` | `MARKET_OPEN` | sessions in which sampling runs (`MARKET_OPEN,PREMARKET,AFTER_HOURS,OVERNIGHT,CLOSED`) |

Plus all Step 4 flags. `FLOW_PL_ENABLED=false` still disables the whole step.

## Rollback

1. `SAMPLE_FLOW_PL_IN_SCANNER=false` — instant, no deploy. Sampling stops; the
   endpoint and existing history are untouched.
2. Full: delete `engine/flow_pl_pipeline.py`, revert `flow_pl_routes.py` to the
   Step 4 version, remove the `app.py` hook + flags. Note the routes file now
   *depends* on the pipeline — reverting one requires reverting both.

## Known limitations

1. **Sampling resolution is the scan interval** (`SCAN_INTERVAL_SECONDS`, 300s
   default). A print that spikes and round-trips inside five minutes still
   records no excursion. This is now a *known, bounded* resolution rather than an
   arbitrary one — a real improvement, not a solved problem. Step 5's sample-size
   thresholds should be read with this in mind: excursions are 5-minute-grid
   observations, not intraday extremes.
2. **First observation still lags the print.** A print at 10:31:02 sampled at
   10:33:00 has ~2 minutes of drift baked into `entry_spot` / `entry_iv`. Labelled
   throughout as "from first observation".
3. **Only `ASSISTANT_TICKER` is sampled.** `_FLOW_PL_SAMPLE_ARGS` passes a single
   ticker; multi-ticker sampling would multiply chain calls and was not assumed.
4. **Sampling and the endpoint both write.** If someone polls `/api/flow_pl`
   during a scan, both record observations — harmless (MFE/MAE only widen an
   envelope; `record_observation` is idempotent in effect), but `samples` counts
   reflect observation frequency, not market activity. Do not use `samples` as a
   feature in Step 5.

## Next dependency

**Step 5 — Historical feature store + similarity engine.** The blocker is now
data, not code: let this run across a few live sessions so `flow_pl_tracking`
holds real excursions to validate leakage tests against, rather than synthetic
fixtures.

Carry into Step 5:
- **limitation 4** — `samples` is an observation artefact; it must never become a
  feature.
- **limitation 1** — excursions are 5-minute-grid, so MFE/MAE are lower bounds on
  true intraday extremes; a "target hit" label derived from them is conservative.
- MFE/MAE remain **post-outcome labels** and must stay out of any pre-decision
  feature vector, exactly as the Step 5 spec's leakage controls require.
