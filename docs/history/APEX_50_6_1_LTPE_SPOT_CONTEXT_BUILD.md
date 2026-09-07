# APEX 50.6.1 — LTPE Spot Context & Next-Session Path Hotfix

## Objective
Allow the Level Transition Probability Engine (LTPE) current-path read model to render during closed/weekend sessions without requiring a live spot, while preserving the evidence-only probability policy and ensuring fallback spot context never enters transition observations/statistics.

## Changes

### 1. Three explicit spot modes
`current_transition_path()` now resolves the path anchor in this order:

1. `EXPLICIT_SPOT` — caller-provided `spot=` query value.
2. `LIVE_SPOT` — current spot from the live runtime snapshot.
3. `LAST_SESSION_SPOT` — most recent persisted HLCE `daily_levels.spot_price` and its session date.
4. `LAST_SESSION_CLOSE` — prior-close institutional level as a last-resort structural read context.

If none are available, the endpoint still returns `NO_SPOT`.

### 2. Read-only safety contract
Path fallback values are display/read-model context only. Responses now include:

- `spot_mode`
- `spot_session`
- `spot_is_observation_input: false`

The path endpoint does not write observations, rebuild statistics, invoke providers, or fabricate probability.

### 3. Explicit replay / what-if spot support
`GET /api/level-calibration/transitions/path` now accepts an optional `spot=<number>` query parameter.

Example:

`/api/level-calibration/transitions/path?direction=UP&spot=7489.52&max_steps=6`

### 4. Version
LTPE component version advances to:

`50.6.1_LEVEL_TRANSITION_PROBABILITY`

The broader APEX stabilization identity remains unchanged.

## Probability policy
No change:

`EVIDENCE_ONLY_NO_FABRICATION`

Fallback path context may determine which institutional levels are displayed above/below the anchor, but it is never used as a synthetic transition observation.

## Validation

- APEX 50.6.0 + 50.6.1 LTPE tests: PASS
- Historical Level Calibration tests: PASS
- APEX 65 stabilization tests: PASS
- Combined targeted regression: **73/73 PASS**
- Repository Python compile: PASS

## Expected weekend behavior
A request such as:

`/api/level-calibration/transitions/path?direction=UP&max_steps=6`

should now return `ok: true` using `LAST_SESSION_SPOT` (or `LAST_SESSION_CLOSE` if no persisted spot exists), with structural path steps visible and probability fields remaining `INSUFFICIENT_HISTORY` until real observations exist.
