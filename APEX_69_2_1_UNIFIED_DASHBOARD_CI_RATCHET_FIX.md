# APEX 69.2.1 — Unified Dashboard CI Ratchet Fix

## Scope
CI-only release-truth repair following APEX 69.2.0. No runtime, decision, execution, dashboard rendering, persistence, or learning behavior changed.

## Fixes
- Replaced stale exact `69.0.x` / `69.1.x` capability-registry assertions with the APEX 69 release-series invariant.
- Removed the historical 68.6 build-name allowlist as a release-ratchet blocker; the test now validates the preserved 68.6 guardrails rather than a finite list of future build names.
- Ratcheted the 69.2 dashboard version assertion to a minimum-version check so patch releases remain valid.
- Updated release metadata and the unified-dashboard capability to 69.2.1.

## Validation
32 relevant release-truth/dashboard regression tests passed locally. Full-suite collection in this container remains unavailable because Flask is not installed; GitHub CI previously demonstrated 2,029 unrelated tests passing and isolated the five assertions repaired here.
