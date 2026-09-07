# APEX 66.8.0 — Confidence Calibration Audit

## Purpose
Audit whether APEX stated confidence is empirically aligned with governed graded outcomes before any confidence calibration is considered for production use.

## Adds
- `/api/effectiveness/confidence-calibration`
- `/api/effectiveness/confidence-calibration/health`
- `/apex_os/confidence-calibration`
- Reliability buckets with observed hit rate and 95% Wilson intervals
- Brier score, log loss, ECE, MCE and AUC
- Overconfidence / underconfidence assessment
- Horizon, setup, session-period and regime calibration breakdowns
- Recent-vs-prior drift diagnostics
- Bayesian-shrunk audit reference probability (display only)

## Governance
This build is read-only. It does not write confidence, change trade decisions, promote calibration, infer missing outcomes, or gain execution authority.

## Codespaces
All code uses repository-relative imports and the existing APEX evidence database resolver. No Render-only or local absolute paths are introduced.
