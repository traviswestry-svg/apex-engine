# APEX 43 — Institutional Intelligence Mesh

## Purpose
Aggregate existing APEX engine evidence into one transparent, governed consensus contract without replacing upstream engines or enabling broker execution.

## Added
- Deterministic Intelligence Mesh engine
- Weighted evidence nodes for gamma, auction, volume profile, order flow, momentum, market structure, expected move, and cross-asset context
- Freshness and reliability penalties
- Coverage, agreement, conflict, net score, and governed confidence
- Mandatory WAIT state for insufficient coverage, weak agreement, material conflict, or low confidence
- `POST /api/intelligence-mesh`
- Command Center mesh visualization
- Explicit `broker_action: NONE`

## Deployment
No database migration or environment variable changes are required.
