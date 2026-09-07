# APEX 69.1 — Flow Excursion Evidence & Identity Closure

## Objective
Close the proven flow-label linkage defect without synthetic backfill or changes to trading/execution authority.

## Changes
- Added `flow_sample_excursions`, keyed by immutable feature-store `sample_id`.
- Sealed flow samples now record/update canonical MFE/MAE envelopes under that exact `sample_id` on every subsequent observation.
- The historical label settler resolves canonical sample-scoped excursions first.
- The legacy coarse key (`ticker|option_type|expiration|direction`) is retained only for lineage.
- Legacy evidence may label a historical vector only when exactly one pending vector maps to the coarse key for that session; ambiguous keys are refused.
- Added lifecycle `excursion_linkage` health telemetry.
- Added canonical-vs-legacy settlement diagnostics including ambiguous legacy vectors.
- No synthetic evidence, no threshold relaxation, no automatic recalibration, no execution authority.

## Historical behavior
Existing ambiguous vectors remain unlabelled unless exact canonical evidence exists. Old singleton vectors may be recovered only where stored legacy excursion evidence maps unambiguously one-to-one.

## Validation
- 274 engine/persistence tests passed.
- 2 Flask-dependent route modules could not be collected because Flask is absent from the validation container.
- Modified Python modules compile successfully.
