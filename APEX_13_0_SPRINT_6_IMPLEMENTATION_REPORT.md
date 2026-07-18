# APEX 13.0 Sprint 6 — Adaptive Learning Foundation

## Baseline

The build used `APEX_13_0_Sprint_5_complete_repository.zip` as the sole repository baseline.

## Implemented

- Governance database schema v5 with idempotent tables and indexes for:
  - offline evaluation manifests
  - candidate approvals and rejections
  - rollback history
  - existing candidate, shadow, drift, and audit records
- Explicit candidate lifecycle:
  - `DISABLED` when evidence gates are closed
  - `DRAFT`
  - `READY_FOR_REVIEW`
  - `SHADOW_ONLY`
  - `REJECTED`
  - `ROLLED_BACK`
- Learning-readiness gate report covering real graded history, history quality, human approval, disabled automatic promotion, and rollback availability.
- Reproducible offline evaluation contracts requiring:
  - dataset hash
  - train, validation, and test split manifests
  - walk-forward validation declaration
  - look-ahead guard declaration
  - baseline and candidate metrics when evidence supports them
  - limitations
- Human approval and rejection records.
- Shadow-mode observation storage separated from production decisions.
- Informational drift-event storage.
- Rollback records with restored-version metadata.
- Expanded immutable governance audit output.
- Adaptive Learning Control Center dashboard.

## APIs added or hardened

- `GET /api/learning/status`
- `GET /api/learning/readiness`
- `GET /api/learning/candidates`
- `GET /api/learning/candidates/<candidate_id>`
- `POST /api/learning/candidates`
- `POST /api/learning/candidates/<candidate_id>/submit`
- `POST /api/learning/candidates/<candidate_id>/evaluate`
- `POST /api/learning/candidates/<candidate_id>/approve-shadow`
- `POST /api/learning/candidates/<candidate_id>/reject`
- `POST /api/learning/candidates/<candidate_id>/shadow`
- `POST /api/learning/candidates/<candidate_id>/rollback`
- `GET /api/learning/evaluations`
- `GET /api/learning/shadow`
- `GET /api/learning/approvals`
- `GET /api/learning/rollbacks`
- `GET /api/learning/audit`
- `GET /api/learning/drift`
- `POST /api/learning/drift`
- `GET /apex_os/adaptive_learning`

## Production safety

- No candidate can change production behavior.
- Automatic promotion remains disabled.
- Candidate approval grants shadow-only status.
- Shadow observations are stored separately from production output.
- Candidate creation fails closed to `DISABLED` until real-history gates pass.
- Offline evaluation cannot proceed without explicit split and leakage-control declarations.
- Rollback and audit records are preserved.
- No synthetic outcomes, evaluation metrics, drift values, or learning claims are generated.
