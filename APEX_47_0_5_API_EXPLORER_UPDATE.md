# APEX 47.0.5 — API Explorer Update

## Scope
- Retains the existing Operations Center API Explorer.
- Auto-discovers all registered Flask routes.
- Enriches routes from the canonical capability registry.
- Displays owner module, capability, version, lifecycle status, auth classification, description, and safe-probe state.
- Adds category and lifecycle-status filtering.
- Adds live route-count, active/shadow, deprecated/quarantined, and safe-probe metrics.
- Adds the APEX 47 release, decision snapshot, evidence readiness, and outcome-grader routes through registry metadata.

## Safety
- Only parameter-free, unauthenticated GET routes are probeable from the page.
- POST, dynamic, and protected endpoints are never called automatically.
- No execution authority was added.

## Files changed
- engine/operations_routes.py
- templates/operations_center.html
- config/apex_capability_registry.yaml
