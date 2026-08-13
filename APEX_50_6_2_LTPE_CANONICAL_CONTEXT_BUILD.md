# APEX 50.6.2 — LTPE Canonical Context Resolution

## Objective
Fix the three LTPE next-session path defects identified in production after APEX 50.6.1:

1. automatic spot resolution could return `NO_SPOT` while canonical APEX price context existed elsewhere;
2. the path could return `steps: []` because LTPE only inspected the live HLCE snapshot instead of the next-session Daily Key Levels / Morning Brief universe;
3. closed/weekend requests could inherit an intraday `LUNCH_SESSION` bucket from the UTC-clock heuristic.

## Implementation

### Canonical spot resolution
`current_transition_path()` now resolves display-only spot context with provenance:

1. explicit `spot=` override;
2. canonical live snapshot spot;
3. latest persisted Morning Brief structured SPX spot;
4. latest persisted HLCE session spot;
5. canonical `prev_close` from the resolved level universe;
6. otherwise `NO_SPOT` with `spot_resolution_attempts` diagnostics.

Fallback spot is strictly read-model context and is always returned with
`spot_is_observation_input: false`. No fallback price is written into LTPE observations or statistics.

### Canonical level universe
The path builder is now session-aware:

- live-session HLCE levels win while the market is active;
- during weekend/next-session preparation, the latest persisted Morning Brief / Daily Key Levels structured level set is preferred;
- the latest persisted HLCE session level set is retained as a final structural fallback.

Morning Brief level kinds are normalized to LTPE/HLCE canonical types. `[FEED REQUIRED]` rows are excluded. Opening Range and Initial Balance levels are additionally blocked from next-session universes when `target_session_date != source_session_date`, preventing prior-session opening structure from leaking into a future session.

### Closed-session context integrity
Next-session/weekend paths now report `session_bucket: NEXT_SESSION_PREP` rather than deriving an intraday bucket such as `LUNCH_SESSION` from wall-clock time. Closed/after-hours contexts use `MARKET_CLOSED` where applicable.

## New response provenance
The path response now includes:

- `spot_mode`
- `spot_session`
- `spot_resolution_attempts`
- `level_universe_mode`
- `level_universe_count`
- `source_session_date`
- `target_session_date`
- `spot_is_observation_input`

## Evidence-only policy preserved
Transition probabilities remain historical-only. A structural path can be displayed before samples exist, but edges return `INSUFFICIENT_HISTORY` / null probability until LTPE has real observations.

## Production-like expected weekend example
With the persisted Monday preparation context used during this build:

- spot: `7489.52`
- spot mode: `CANONICAL_NEXT_SESSION_SPOT`
- source session: `2026-07-31`
- target session: `2026-08-03`
- level universe: `NEXT_SESSION_DAILY_KEY_LEVELS`
- session bucket: `NEXT_SESSION_PREP`
- next distinct upward levels: `7512.04 prev_day_high` → `7529.00 expected_move_high`

The 7490 call-wall cluster is within LTPE's configured minimum distinct-target gap around the 7489.52 source context, so it is treated as part of the current price cluster rather than the next distinct path step.

## Validation
- 12/12 LTPE 50.6.0–50.6.2 focused tests: PASS
- 76/76 targeted HLCE/LTPE/APEX 65 regression tests: PASS
- repository Python compilation: PASS
- production-like weekend path simulation: PASS
- observation contamination check: PASS (`observations` remains unchanged)

No trading, risk, execution, broker, or signal logic changed.
