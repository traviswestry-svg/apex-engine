# APEX 69.9.5 — Five-Minute Observation Integrity & Regret Eligibility Closure

## Purpose
69.9.5 closes the measurement defect exposed by 69.9.4: a Trigger Observatory price sample arriving after the configured five-minute window could previously contaminate MFE/MAE, favorable-rate, timing, visualization, and regret diagnostics.

This release is observational and integrity-only. It does not change any blocker, confidence score, conviction threshold, consensus weight, evidence eligibility rule, calibration state, execution authority, or broker state.

## Five-Minute Window Contract
The canonical Trigger Observatory window remains 300 seconds.

Every persisted price sample is now classified from its actual timestamp relative to the trigger:

- `IN_WINDOW` — `0 <= elapsed_seconds <= observation_window_seconds`
- `LATE` — `elapsed_seconds > observation_window_seconds`
- `PRE_TRIGGER` — timestamp precedes the trigger

A matured trigger with no valid in-window sample is represented as `OBSERVATION_WINDOW_INCOMPLETE`.

Trigger-level integrity distinguishes:

- `IN_WINDOW`
- `LATE`
- `WINDOW_MISSED`
- `OBSERVING`
- `NOT_APPLICABLE`

Non-directional/event-only triggers are not forced into a five-minute excursion contract.

## Historical Reconciliation
69.9.5 recomputes historical Trigger Observatory excursion fields only from already persisted raw in-window samples.

For each trigger it derives:

- in-window observation count;
- late observation count;
- pre-trigger observation count;
- window MFE;
- window MAE;
- window outcome;
- first/last in-window observation timestamps;
- first late observation timestamp.

Legacy aggregate MFE/MAE/outcome values are not trusted when raw observation evidence is available. A late-only sample cannot become a five-minute favorable or adverse outcome.

No missing price path is reconstructed or interpolated.

## Live Observation Closure
`observe_price()` no longer allows the first observation after 300 seconds to become the five-minute terminal measurement.

A late first observation is retained as `LATE` evidence but the trigger becomes:

`OBSERVATION_WINDOW_INCOMPLETE`

with no five-minute MFE/MAE fabricated from that late price.

If valid in-window observations already exist and a later sample arrives, the trigger terminalizes using only those previously persisted in-window observations.

## Effectiveness & Predictive Validation
Five-minute effectiveness now excludes late-only and missed-window triggers from:

- five-minute observed counts;
- five-minute favorable rate;
- MFE;
- MAE;
- time-to-favorable;
- time-to-adverse;
- time-to-threshold.

`/api/triggers/predictive-validation` advances to:

`apex.predictive_validation.v6`

It includes `observation_window_integrity` with trigger and sample coverage truth.

## Regret Eligibility
`apex.abstention_regret.v2` requires a valid `IN_WINDOW` excursion before a directionally correct NO_TRADE can qualify as `POTENTIAL_BLOCKER_REGRET`.

Late-only and missed-window observations remain:

`DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE`

unless other valid in-window evidence exists.

## Persisted Movement Threshold Recovery
69.9.5 retains the existing threshold hierarchy and adds narrowly governed recovery from explicit target-named values already persisted in the canonical historical decision snapshot.

Priority:

1. trigger `target1_reference`;
2. explicit canonical target fields such as persisted `tp1` / `target1` / `target_1` / `first_target` / `primary_target`;
3. persisted `dynamic_state_policy.required_boundary_margin_points`;
4. `UNAVAILABLE`.

Generic supports, resistances, or arbitrary decision levels are never promoted into a regret threshold by inference.

## Market-Open Time Buckets
The prior broad `LATER_MARKET_OPEN_60_PLUS` cohort is replaced by:

- `MARKET_OPEN_60_90`
- `MARKET_OPEN_90_120`
- `MARKET_OPEN_120_180`
- `MARKET_OPEN_180_PLUS`

The existing 0–15, 15–30, and 30–60 minute buckets remain.

## Canonical Grader Horizon Verification
`engine.outcome_grader` advances to `apex.outcome_grader.v2` / engine version 69.9.5.

New grades persist:

- `forward_observed_at`;
- `window_start_at`;
- `window_end_at`;
- `price_sample_count`;
- `price_query_window_enforced=true`.

The new `horizon_integrity()` diagnostic independently reports:

- configured default horizon;
- expected canonical horizon of 300 seconds;
- stored horizon distribution;
- stored-horizon mismatches;
- outcome-horizon mismatches;
- forward timestamps available for direct verification;
- forward timestamps inside/outside the stored horizon;
- legacy grades for which forward timestamps were not historically persisted.

The grader's price query remains bounded to:

`decision observed_at <= price observed_at <= decision observed_at + horizon_seconds`

## New API
`GET /api/triggers/observation-integrity?symbol=SPX`

Returns both:

- Trigger Observatory five-minute window integrity;
- canonical outcome-grader horizon integrity.

## Dashboard
Premium Discipline Command Center now surfaces:

- in-window trigger count;
- late-only trigger count;
- missed-window count;
- observing count;
- in-window / late / pre-trigger sample counts;
- canonical grader horizon status;
- stored horizon mismatches;
- out-of-window canonical forward timestamps.

## Authority
69.9.5 does not:

- modify `THESIS_INVALIDATED`;
- modify any other blocker;
- modify confidence;
- modify thresholds;
- modify consensus weights;
- activate calibration;
- grant execution authority;
- mutate broker state.

The release repairs measurement truth before any behavioral blocker decision is considered.
