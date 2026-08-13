# APEX 50.2.1 — Morning Brief Formatting Hardening

## Runtime failure fixed

`ValueError: Unknown format code 'f' for object of type 'str'`

The Expected Move adapter can correctly return a categorical quote-quality confidence such as `HIGH`. The Morning Brief renderer previously sent every present value through a floating-point formatter, so the valid string confidence crashed report generation.

## Changes

- Added strict finite-number detection before numeric formatting.
- Added a safe general report formatter that preserves strings such as `HIGH`, `neutral_gamma`, and `NOT_APPLICABLE`.
- Added safe signed-distance formatting.
- Hardened ranked-level importance formatting.
- Preserved `[FEED REQUIRED]` for genuinely absent feed values.
- Added regression tests for categorical Expected Move confidence and nonnumeric report values.

## Deployment

Replace `engine/daily_key_levels.py`, deploy, and regenerate the brief with:

`/api/morning-brief?refresh=1`

## Validation

- Python compilation: PASS
- Focused tests: 4 passed
