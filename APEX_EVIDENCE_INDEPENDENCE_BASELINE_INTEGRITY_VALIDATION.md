# APEX — Evidence Independence & Baseline Integrity Validation

**Source:** user-supplied `apex-engine-main(20261106-121700).zip` (November 6, 2026).  
**Disposition:** LIMITED, VERIFIED FIX ONLY; **not** an authorization for a major build or production promotion. Canonical version unchanged.  
**Scope:** existing Flow Surprise, feature-store historical reader, market-driver concentration, confirmation scanner, and Phase 19 Trade Director. No actual market performance dataset was supplied for incremental predictive tests.

## Acceptance criteria

| Acceptance criterion | Finding | Disposition |
|---|---|---|
| 1. Correlated flow, skew, and volatility cannot artificially inflate conviction | **Not demonstrated.** `engine/trade_director_decision.py` uses weighted votes from institutional flow, options, cross-asset, MTF, etc. without explicit underlying source-family overlap tests. `engine/confirmation_scanner.py` separately weights ES and SPY and VIX and VVIX. The multiplier is capped at 1.15 but may still be raised by redundant measurements. A synthetic committee example rose from 72.0 to 86.0 when additional aligned engines were supplied, without independence metadata; this demonstrates sensitivity to duplicated inputs, not proven live double-counting. | **Open evidence-independence gap.** No production scoring changes justified before documenting concrete lineage/overlap and measuring conditional effects. |
| 2. Flow Surprise uses valid decision-time history with no future/same-session contamination | **Failed in uploaded version and reproduced.** `engine/flow_surprise.py` selected on time bucket and DTE class only. `engine/feature_store_db.py::historical_feature_rows` used newest rows without an earlier-session cutoff. 20 synthetic same-day rows or 20 future-day rows each yielded `AVAILABLE` at an earlier decision. | **Minimal targeted fix included**: earlier market-session-only database filtering before LIMIT, duplicate evaluator exclusion and timestamp-to-session coherence checks, updated synthetic legacy fixtures, and four new regression tests. Existing read-only flags remain unchanged. |
| 3. Index concentration/implied correlation provide incremental information beyond breadth, VIX, VVIX, cross-asset | **Not demonstrated** by this repository. `engine/market_drivers.py` tracks 20 approximate, static mid-2026 constituent weights and concentration-style leadership/breadth context; it is not a verified time-varying SPX concentration series. No independently sourced implied-correlation observation and no walk-forward ablation comparing baseline features versus baseline plus the two candidate factors were found. | **Research-only, not promotion-eligible.** Avoid synthetic implied-correlation estimates or treating static constituent weights as fresh index metadata. Collect point-in-time underlying weights, option-implied basket and component variance with timestamp/expiry consistency, and independent breadth/volatility factors, then test forward out-of-sample incremental contribution. |

## Reproduction and fix

- Before patch: 20 same-session samples -> `AVAILABLE` / n=20; 20 future-session samples -> `AVAILABLE` / n=20; 20 prior-session samples -> `AVAILABLE` / n=20. **The first two are point-in-time failures**.
- After patch: only records with a validated session date **strictly earlier** than target session, and a decision timestamp consistent with their stated US/Eastern session, qualify. The optional `before_session_date` SQL cutoff is applied before `LIMIT` to prevent newer records from crowding out eligible historical history.
- Keeps the existing sample count and percentile formula. **This does not prove statistical independence of samples**; multiple prior-session clusters can still contribute correlated observations, so significance/confidence must not be treated as validated.
- No new environment variables, APIs, trading authority, scoring weights, data-provider calls, or schema migrations. Existing archived Flow Surprise records stay immutable; no historical recomputation/backfill.

## Audit probes and test results

- Focused original and new Flow Surprise regressions: **12 passed**.
- Confirmation scanner, Trade Director, consolidation, gamma/flow related selected tests: **36 passed**.
- Gamma temporal integrity, canonical evidence identity, cluster feature persistence and candidate regressions: **69 passed**.
- `compileall` for four changed runtime modules: **passed**.
- Full `pytest -q --maxfail=1` is **blocked during collection** by missing `flask` dependency in this container (`tests/test_adaptive_confidence_calibration.py` -> `engine/institutional_decision_integrity.py`). Thus this **is not CI/release certified**.

### Independence probe details

- `scan_confirmation(BULLISH, ES only)` => multiplier 1.15; ES+SPY => 1.15 (same ceiling). VIX only => 1.15; VIX+VVIX => 1.15. This shows a cap, **not de-duplication**: votes and confirmation counts still increase.
- `build_decision_intelligence` synthetic identical high-confidence directions: flow alone => consensus 72.0/coverage 20%; flow+options => 74.8/28%; flow+options+cross asset+MTF => 86.0/60%. Hypothetical correlated sources can increase the score. The probe does not prove these specific engines share identical live observations, and the decision gate remained `WATCH` in this synthetic setup.

## Recommended next evidence collection (no major build)

1. Establish evidence family/lineage for every vote: primitive vendor feed, instrument, observation timestamp, source event IDs, source snapshot hash, and transforms. Run pairwise overlap and same-source replay probes, distinguishing direct duplicates from correlated market indicators.
2. On existing frozen historical samples, measure Flow Surprise baseline distinct session counts, cluster clustering by session, and conditioning coverage; never rebuild old frozen features with newly discovered records.
3. Gather source-authenticated and timestamp-aligned SPX constituent weights, component implied variances and index implied variance. Pre-register incremental metrics (out-of-sample log loss/Brier or range error, stability, abstention changes, transaction timing); compare *baseline breadth+VIX+VVIX+cross asset* with *baseline+concentration*, *baseline+implied correlation*, *both*. Use chronological walk-forward splits and session-level uncertainty intervals. Decline promotion if missing or nonincremental.

**Release gate:** The verified Flow Surprise fix is a candidate only. Verify the entire CI/release governance suite in a fully provisioned environment, including gamma-transition temporal regressions and baseline behavior. Do not change official trading authority or promote new predictive factors from this audit.
