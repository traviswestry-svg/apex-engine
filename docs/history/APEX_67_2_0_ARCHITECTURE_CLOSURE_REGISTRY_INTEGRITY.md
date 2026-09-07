# APEX 67.2.0 — Architecture Closure & Registry Integrity

Closes release and architecture identity drift found in the August 17 weekend audit.

## Changes
- release manifest: 67.2.0 / APEX 67 / current build name / 2026-08-17
- capability registry now includes 66.7, 66.8, 67.0, 67.1, and 67.2 systems
- Breadth Regime component version corrected to 66.9.0
- canonical release-manifest capability version aligned to 67.2.0
- read-only Architecture Integrity endpoint and dashboard
- CI tests ratchet release metadata, registry completeness, module integrity,
  duplicate routes, and historical executable-source contamination
- one-time Codespaces cleanup script removes only the four audited historical
  executable source-copy directories

## Endpoints
- `/api/architecture-integrity`
- `/apex_os/architecture-integrity`

## Codespaces cleanup
Run once after overlaying this build:
`python scripts/apex_67_2_repo_cleanup.py`
