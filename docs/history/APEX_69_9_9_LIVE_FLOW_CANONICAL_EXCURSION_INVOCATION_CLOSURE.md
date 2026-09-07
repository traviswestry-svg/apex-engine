# APEX 69.9.9 — Live Flow Canonical Excursion Invocation Closure

## Purpose
Close the observed production gap where live flow feature rows persisted while canonical excursion
capture telemetry remained at zero.

## Root cause
Production delegated canonical excursion capture across a second handoff by calling
`feature_store_writer.write_samples(..., defer_excursion_capture=True)`. The writer already
contains the correct post-persistence canonical capture path. 69.9.9 removes that unnecessary
deferred production boundary.

## Runtime change
The scanner now calls `write_samples(..., defer_excursion_capture=False)`. The feature writer:
1. persists the immutable flow feature;
2. publishes the canonical sample identity;
3. invokes canonical excursion capture with the same sample_id and genuine live P/L mark;
4. records capture attempts/inserts/updates/missing-P/L/errors.

No sample identity is reconstructed.

## Guardrails
- no historical excursion backfill;
- no synthetic P/L or marks;
- no settlement requirement relaxation;
- no grading threshold change;
- no trade-decision authority change;
- no execution-authority change;
- deferred capture remains available only for compatibility/tests, not production.

## Expected production evidence
After eligible live flow samples:
`capture_attempts > 0`, `excursions_inserted > 0` or `excursions_updated > 0`,
and `sample_excursions > 0`.

After maturity and normal settlement:
`canonical_excursion_rows_found > 0`, `labelled > 0`, and eventually
`flow_features.graded > 0`.
