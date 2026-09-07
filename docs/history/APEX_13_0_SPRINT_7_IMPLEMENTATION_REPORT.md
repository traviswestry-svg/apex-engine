# APEX 13.0 Sprint 7 Implementation Report

## Scope
Implemented governed offline weight optimization and shadow evaluation on top of the Sprint 6 adaptive-learning control plane.

## Added
- `engine/offline_weight_optimization.py`
- Chronological 60/20/20 train, validation, and untouched holdout split
- Deterministic grid search over confidence and conviction weights
- Validation-set candidate selection using Brier score
- Baseline-versus-candidate holdout comparison
- Reproducible dataset and integrity hashes
- Automatic registration in the governed candidate registry
- Mandatory offline evaluation manifest registration
- Descriptive shadow scorecards with no outcome claims
- Research dashboard and APIs

## Safety
- Production configuration is never read-modified-written.
- Every run reports `production_effect: NONE`.
- Candidate promotion remains unavailable.
- Human approval authorizes shadow observation only.
- Missing or insufficient real outcomes return `INSUFFICIENT_HISTORY`.
- Holdout results are descriptive and do not imply causal or future performance.

## APIs
- `GET /api/learning/optimization/status`
- `POST /api/learning/optimization/run`
- `GET /api/learning/optimization/runs`
- `POST /api/learning/candidates/<candidate_id>/shadow-scorecard`
- `GET /api/learning/shadow-scorecards`
- `GET /apex_os/offline_optimization`
