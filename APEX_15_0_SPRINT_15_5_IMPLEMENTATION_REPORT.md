# APEX 15.0 Sprint 15.5 Implementation Report

## Institutional Research Lab and Alpha Attribution

Implemented a governed, offline research environment for registering candidate indicators, filters, playbooks, confidence models, execution policies, strategies, and data features. Added immutable research runs, deterministic candidate comparison, descriptive subsystem alpha attribution, and promotion-readiness assessments.

### New module
- `engine/institutional_research_lab.py`

### New database tables
- `research_candidates`
- `research_runs`
- `alpha_attribution_records`
- `promotion_readiness_assessments`

### New API surface
- `GET /api/research-lab/status`
- `POST/GET /api/research-lab/candidates`
- `POST/GET /api/research-lab/runs`
- `POST /api/research-lab/compare`
- `POST /api/research-lab/readiness`
- `POST/GET /api/alpha-attribution/records`
- `GET /api/research-lab/dashboard`

### Dashboard
- `/apex_os/research_lab`
- `/apex_os/alpha_attribution`

### Safety contract
The lab is offline-only. Candidate activation, automatic promotion, live decision feedback, and broker effects are disabled. Attribution is descriptive and makes no causal claim.
