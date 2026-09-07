# APEX 69.7.0 — Failed Breakdown Lifecycle Intelligence Foundation

## Scope

APEX 69.7.0 adds a persistent, chronological and observational-only lifecycle
for failed-breakdown research. It recognizes and records the sequence from a
significant level through approach, downside displacement, sweep, reclaim and
confirmation. It does not create trade direction, alter consensus, authorize
execution or automatically promote learned thresholds.

## Runtime behavior

- Capture occurs after the canonical decision has been frozen.
- Production observations are scanner-owned.
- GET routes are read-only and do not initialize missing stores.
- The POST observation route is available only while Flask is in test mode.
- Missing price or level evidence produces an explicit unavailable/watching
  state rather than fabricated lifecycle evidence.

## Persistent contracts

- `fbd_observations`: immutable normalized price observations.
- `fbd_lifecycles`: one record per significant level lifecycle.
- `fbd_events`: chronological state transitions with decision-time evidence.

The lifecycle records displacement, sweep depth, sweep time, reclaim time,
confirmation time, invalidation, optional ES/SPX basis provenance and the first
two structural targets.

## Lifecycle

`WATCHING_LEVEL -> APPROACHING -> ELEVATOR_DOWN_CONFIRMED -> SWEPT -> RECLAIMED
-> CONFIRMATION_PENDING -> ENTRY_ELIGIBLE -> TP1_REACHED -> RUNNER_ACTIVE`

Terminal outcomes include `NO_RECLAIM`, `RECLAIM_FAILED`, `ACCEPTANCE_FAILED`,
`INVALIDATED`, `EXPIRED`, `DATA_UNAVAILABLE`, and `COMPLETED`.

## API

- `GET /api/failed-breakdown/capability`
- `GET /api/failed-breakdown/state`
- `GET /api/failed-breakdown/history`
- `POST /api/failed-breakdown/observe` (test-mode only)

## Governance

- Decision authority: none.
- Execution authority: none.
- Production effect: observational only.
- Automatic promotion: disabled.
- Newsletter statistics and institutional-intent narratives are not encoded as
  facts or priors.
