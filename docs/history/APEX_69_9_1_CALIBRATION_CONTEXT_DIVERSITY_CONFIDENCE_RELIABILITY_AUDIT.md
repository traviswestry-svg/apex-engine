# APEX 69.9.1 — Calibration Context Diversity & Confidence Reliability Audit

## Purpose
APEX 69.9.1 converts the 69.9.0 predictive-validation findings into a read-only audit of calibration context quality, confidence reliability, and cohort composition.

## Calibration Context Diversity
The build audits each governed calibration field as:
- `UNKNOWN` — all graded observations are missing/unknown.
- `CONSTANT` — a known value exists but does not vary across graded contexts.
- `VARIABLE` — multiple known values exist across graded contexts.
- `AVAILABLE` — the field is structurally available but no graded sample is present.

The audit reports source provenance, unknown rate, known-value diversity, and value counts. If aggregate history exceeds the governed minimum while no calibration field varies, the surface reports `CONTEXT_QUALITY_DEFICIENT`.

## Confidence Reliability
Raw conviction remains an ordinal decision score and is not redefined as an empirical probability.

The audit provides:
- canonical graded sample size by confidence band;
- observed win rate with Wilson 95% intervals;
- five-minute favorable rate, MFE, and MAE;
- minimum-sample-gated monotonicity checks;
- explicit `NON_MONOTONIC_OBSERVED_OUTCOMES` when a higher comparable confidence band has a lower observed win rate.

ECE, Brier score, and other probability-calibration metrics remain disabled because the current confidence contract does not define raw conviction as event probability.

## Cross-Cohort Decomposition
The predictive-validation surface now exposes:
- direction × confidence;
- direction × blocker;
- confidence × blocker;
- session × direction;
- canonical grade horizon × direction.

Canonical session and grade-horizon context are joined from the evidence ledger by `decision_id`, avoiding a trigger database migration.

## Authority
This build is observational only. It does not mutate:
- trade decisions;
- evidence eligibility;
- confidence;
- thresholds;
- consensus weights;
- calibration activation;
- execution authority;
- broker state.

Existing human-governed calibration integrity gates remain unchanged.
