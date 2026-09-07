# APEX 65.6.5 — Version / Build Identity Integrity Hotfix

## Objective
Remove ambiguity between the deployed APEX product release, subsystem/component versions, and the active production-stabilization build without changing trading behavior.

## Findings
APEX legitimately carried several version domains but exposed them through overlapping generic fields. The canonical release manifest reports APEX 48.2.0, the historical-level/morning-brief component reports 50.5.0, data-quality reports its own 50.1 schema/version, and the active stabilization line is 65.x. The Morning Brief also stamped an older 50.4.2.1 patch name into `data_quality.application_version`, which made production diagnostics look internally inconsistent.

## Changes
- Added `engine/build_identity.py` as the canonical metadata-only identity layer.
- Active stabilization build is `65.6.5`.
- Runtime diagnostic endpoints now expose `build_identity`, `runtime_release_version`, `component_version`, and `stabilization_build` while retaining legacy `version` fields for compatibility.
- Morning Brief now marks its generic `version` as component-scoped and exposes explicit runtime/build identity.
- `data_quality.application_version` now means the deployed runtime release; the previous patch identifier is preserved as `legacy_application_version`.
- Data-quality engine/schema version remains independently available as `component_version` / `schema_version`.

## Guardrails
- No signal logic changed.
- No scoring or probability logic changed.
- No market-data calculations changed.
- No risk logic changed.
- No broker or order behavior changed.
- Existing legacy `version` fields are preserved for dashboard/API compatibility.
