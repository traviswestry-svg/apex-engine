# APEX 66.1.1 — Active Level Lifecycle Reconciliation Cleanup

## Objective
Remove artificial retire/reactivate churn from APEX 66.1 live active-level publication without changing level generation, HLCE interaction detection, calibration math, decisions, or execution.

## Root cause
APEX 66.1 treated each authoritative mutable domain as replace-all: it retired every active row for that kind, then immediately reactivated matching prices. This produced correct final active state but misleading lifecycle telemetry and unnecessary writes (`retired: 47`, `reactivated: 45` on a largely unchanged cycle).

## Repair
`publish_live_levels()` now performs a true set-diff per authoritative canonical kind:

- CURRENT ∩ NEW → remain active; refresh `observed_at` and provider metadata in place.
- CURRENT - NEW → retire only genuinely removed prices and set `valid_to`.
- NEW - CURRENT → reactivate a matching historical inactive row if it truly reappeared; otherwise create a new revision.
- Static/non-authoritative kinds remain untouched.
- Input rows are de-duplicated by canonical `(kind, price)` before reconciliation.

New telemetry:
- `refreshed`
- `unchanged`
- `created`
- `reactivated`
- `retired`

Expected steady-state publication now resembles:
`refreshed: N, created: 0, reactivated: 0, retired: 0`
rather than retiring/reactivating the full mutable universe every minute.

## Version
`66.1.1_ACTIVE_LEVEL_RECONCILIATION`

## Files changed
- `engine/canonical_session_context.py`
- `engine/live_active_level_publisher.py`
- `tests/test_apex_66_1_live_active_level_publication.py`

## Validation
51/51 relevant tests passed across:
- 66.1 live active-level publication
- 66.0 active-level registry
- 65.9 interaction lifecycle
- HLCE historical calibration
- LTPE probability / spot / failsafe / canonical-context suites
- transition learning activation

## Safety / authority
- Decision influence: NONE
- Execution influence: NONE
- No probability changes
- No HLCE interaction-rule changes
- No scanner lifecycle changes
- No provider selection changes
