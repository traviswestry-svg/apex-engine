# APEX 69.8.2 — Trigger Linkage & Calibration Readiness Verification

## Purpose

69.8.2 closes the operator-observability gaps identified after 69.8.1 without changing trading behavior. It binds canonical Trigger Observatory records to the persisted historical evidence `decision_id`, exposes grounded reasons for blocked canonical observations, distinguishes aggregate graded-history readiness from governed per-context calibration activation readiness, and surfaces trigger observation maturation.

## Changes

- Canonical Trigger Observatory capture now receives the `decision_id` returned by the already-completed historical evidence capture.
- `record_canonical_snapshot` also resolves the persisted historical capture ID directly from the snapshot as a safe fallback.
- Blocked canonical triggers expose explicit canonical blocking conditions plus deterministic finalized-state reasons such as `CONVICTION_BELOW_ACTIONABLE_THRESHOLD` and the canonical decision status.
- Learning readiness now reports calibration governance mode, graded decision contexts, candidate states, active calibration count, activation eligibility/state, and a plain-language readiness reason.
- Learning readiness separately reports trigger maturation: observing, matured, overdue-observing, and triggers with persisted price observations.
- Premium Discipline displays the selected trigger's canonical decision ID and the new calibration/maturation diagnostics.
- Historical feature tests no longer pin the repository's current release number to the release at which the feature was introduced. They verify version consistency, minimum feature version, and preserved guardrails instead.

## Authority boundaries

- Automatic calibration activation remains disabled.
- Human governance remains required for bounded calibration activation.
- Trigger linkage, blocked-reason visibility, calibration readiness verification, and observation maturation are observational only.
- No broker mutation or execution authority is introduced.
- No entry, target, stop, confidence, consensus, gamma, HLCE, Tick Momentum, or Microstructure behavior is changed.

## Validation

- 24/24 targeted 69.8.x and release-truth/consolidation tests passed.
- 30/30 affected calibration, gamma, outcome-attribution, and failed-breakdown tests passed.
- Python compilation passed.
- Premium Discipline JavaScript syntax check passed.
- Flask-dependent route collection is environment-blocked because Flask is not installed in the build container; the repository declares Flask as a dependency.
