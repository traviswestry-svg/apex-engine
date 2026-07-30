# APEX 50.4.1 — Validation & Consistency Hotfix

## Purpose
Corrects the false Morning Brief health classification and exposes the consistency issues found during the APEX 50.4 production validation run.

## Changes
- Adds explicit Executive 5-section and Full 17-section validation profiles.
- Treats Sections 1, 2, 15, 16, and 17 as the required Executive profile.
- Marks missing required sections, unknown gamma regime, implausibly distant gamma references, identical gamma fields, slow generation, or inconsistent settlement metadata as warnings.
- Derives `HEALTHY`, `DEGRADED`, and `FAILED` from actual errors and warnings.
- Adds stage-level timing for providers, Expected Move, profile-history load/save, brief generation, data quality, validation, and total duration.
- Adds explicit raw ES settlement, SPX-normalized settlement, basis adjustment, and normalization method.
- Adds centralized Morning Brief and validation version constants.
- Reports profile memory as `INITIALIZING` on the first saved session instead of treating it as an error.
- Disables directional gamma logic when the dealer gamma regime is unknown.

## Deployment
Overlay the files in this ZIP onto the deployed APEX 50.4 repository and redeploy.

## Verification
1. Request `/api/morning-brief?refresh=1`.
2. Request `/api/morning-brief/validation`.
3. Confirm the response version is `50.4.1_VALIDATION_CONSISTENCY_HOTFIX`.
4. Confirm `section_profile` is `EXECUTIVE_5` and required sections are `1,2,15,16,17`.
5. Review `timing`, `gamma_state`, `settlement_normalization`, and `warnings`.
