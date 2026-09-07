# APEX 48.1.0 — Canonical Version Unification

## Purpose
Remove the final split-version behavior from the Operations Center. Product-level readiness, metrics, API inventory, release-manifest, health, and release responses now derive their active APEX identity from `config/apex_release_manifest.json`.

## Behavior
- `/api/system/readiness` reports `48.1.0`.
- `/api/system/metrics` reports `48.1.0`.
- Embedded observability metrics report `apex_version: 48.1.0`.
- The historical observability identity is preserved as `component_version: 10.1.0_PRODUCTION_OBSERVABILITY`.
- Operations Center API inventory and diagnostics derive their version from the same release authority.
- Release-manifest routes no longer retain a separate hard-coded `47.0.6` value.

## Guardrails
This release changes reporting only. It does not alter trade decisions, scanner scheduling, execution authority, adaptive weights, or database contents.
