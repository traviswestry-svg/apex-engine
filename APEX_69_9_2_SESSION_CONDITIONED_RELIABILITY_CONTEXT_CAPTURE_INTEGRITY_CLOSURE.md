# APEX 69.9.2 — Session-Conditioned Reliability & Calibration Context Capture Integrity Closure

## Purpose
69.9.2 closes the calibration-context capture defect exposed by 69.9.1 and extends predictive validation so confidence is evaluated within session and decision-class cohorts before any behavioral interpretation.

## Context Capture Integrity
- Historical evidence capture now reconstructs observational dynamic state from the exact finalized production composition snapshot after the canonical decision is complete.
- The exact dynamic-state policy already embedded in the finalized institutional decision is preserved when available.
- Calibration context now records field-level provenance: `SOURCE_PRESENT`, `SOURCE_MISSING`, or `NORMALIZED_UNKNOWN`.
- Missing boolean fields remain unknown in context JSON rather than being silently interpreted as `false`.
- Source-verified calibration summaries no longer count missing/unknown rows as valid false-state buckets.
- Calibration governance challenger/incumbent comparisons exclude unverified context rows for the dimension being tested.

## Historical Backfill
`POST /api/triggers/context-backfill`

The endpoint is preview-first:
- omitted or `apply=false`: reports recoverable decisions/fields only;
- `apply=true`: updates historical calibration context only where the canonical persisted decision snapshot contains a source-present value.

Missing historical source values are never inferred or synthesized. This endpoint has no decision, execution, or broker authority.

## Session-Conditioned Reliability
`GET /api/triggers/predictive-validation`

Schema advances to `apex.predictive_validation.v3` and adds:
- confidence × session;
- direction × confidence × session;
- blocker × session;
- per-session confidence monotonicity diagnostics;
- decision-class effectiveness;
- actionable trade vs observational NO_TRADE separation;
- release cohort attribution when `apex_release_version` is available;
- grade-horizon × direction retained.

## Release Cohorts
New historical snapshots persist canonical `apex_release_version` for forward cohort attribution. Older observations remain `UNKNOWN` unless a canonical persisted snapshot already contains a release value.

## Authority
69.9.2 is observational and calibration-integrity only. It does not change:
- trade decisions;
- confidence scores;
- thresholds;
- consensus weights;
- evidence eligibility;
- calibration activation;
- execution authority;
- broker state.

Automatic calibration activation remains disabled and existing human-governed integrity gates remain unchanged.
