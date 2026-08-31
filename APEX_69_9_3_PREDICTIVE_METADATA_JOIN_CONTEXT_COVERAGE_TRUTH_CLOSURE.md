# APEX 69.9.3 — Predictive Metadata Join & Context Coverage Truth Closure

## Purpose
69.9.3 is a narrow corrective release for the production findings exposed by 69.9.2. It repairs predictive metadata joins and prevents partial historical context recovery from being presented as complete calibration-context health.

## Predictive Metadata Join Closure
`GET /api/triggers/predictive-validation` advances to `apex.predictive_validation.v4`.

The evidence-ledger metadata loader now:
- removes the undefined mapping-helper failure in legacy snapshots without `apex_release_version`;
- isolates parsing failure per decision row;
- preserves every valid metadata join when another historical snapshot is malformed;
- keeps release version `UNKNOWN` when no canonical source exists rather than fabricating one.

The response now includes `metadata_join` diagnostics:
- `canonical_graded_links`;
- `graded_links_with_decision_id`;
- `metadata_joined`;
- `metadata_missing`;
- `metadata_join_rate_pct`;
- `session_known` / `session_unknown`;
- `decision_class_joined`;
- `grade_horizon_joined`;
- `release_version_known` / `release_version_unknown`;
- loaded metadata-row counts;
- bounded parse-error diagnostics.

A single malformed historical snapshot can no longer erase all valid session, decision-class, release, and grade-horizon metadata.

## Context Coverage Truth
`calibration_context_quality` advances to `apex.calibration_context_diversity.v3`.

Each audited field now reports source-present percentage. Overall coverage reports:
- complete-coverage field count;
- partial-coverage field count;
- missing-coverage field count;
- whether context coverage is complete;
- whether the system is in partial historical recovery.

Quality states now distinguish:
- `CONTEXT_QUALITY_DEFICIENT` — enough history exists but no source-verified field varies;
- `PARTIAL_CONTEXT_RECOVERY` — genuine variation exists, but historical source coverage is incomplete;
- `CONTEXT_DIVERSITY_PRESENT` — source-verified variation exists and audited-field coverage is complete.

Thus one variable field over a minority of historical samples is no longer presented as fully recovered context health.

## Dashboard
Premium Discipline now surfaces:
- metadata join state and join rate;
- joined session and grade-horizon counts;
- metadata parse-error count;
- complete / partial / missing calibration-field coverage;
- `PARTIAL_CONTEXT_RECOVERY` as an amber operator state.

## Authority
69.9.3 remains observational and truth-closure only. It does not change:
- trade decisions;
- confidence scores;
- thresholds;
- consensus weights;
- evidence eligibility;
- calibration activation;
- execution authority;
- broker state.

Automatic calibration activation remains disabled.
