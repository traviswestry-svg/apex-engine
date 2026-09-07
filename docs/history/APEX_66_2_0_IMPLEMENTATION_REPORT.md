# APEX 66.2.0 — Execution Integrity & Level-Source Coverage

## Authoritative baseline audit
This build used only the uploaded repository ZIP as source. The repository contains implementation reports through APEX 66.1.2 even though canonical release metadata remained stale (`48.2.0` manifest and `50.5.0` engine/version identity). The next release is therefore APEX 66.2.0; the repository was not downgraded to the older 50.x line.

The uploaded ZIP did not contain a root `.gitignore`. A real root `.gitignore` has been restored with SQLite database and sidecar exclusions.

## Execution-boundary audit
A repository-wide broker mutation scan found one remaining direct broker mutation outside `engine/execution/canonical_execution.py`: the legacy Phase 10 Trade Director management confirmation route in `app.py` called `ETradeAdapter.place_order()` directly after its own exact-confirmation workflow.

APEX 66.2.0 closes that escape hatch without rewriting the already-hardened single-leg entry, complex strategy, order-change, or cancel paths.

### New canonical management/exit boundary
`CanonicalExecutionBoundary` now supports bound risk-reducing management previews and SELL_CLOSE submission with:
- broker preview binding
- preview expiration
- post-preview intent mutation detection
- held-position quantity binding
- final exit-quantity risk revalidation immediately before broker I/O
- configured human confirmation enforcement
- duplicate submission prevention
- fail-closed action validation (`SELL_CLOSE` only)

The Phase 10 prepare route registers the broker preview with the canonical boundary. The Phase 10 confirm route now calls `execute_management_exit()` instead of the E*TRADE adapter directly.

A static regression test now fails if `place_order`, `place_complex_order`, `place_change_order`, or `cancel_order` is called outside the canonical boundary or broker adapter implementation.

## Authentication and authorization
The canonical Flask application already installs application-wide fail-closed authentication through `engine.auth.install_auth(app)` before route registration. Every non-exempt execution route therefore remains authenticated at the application boundary. This build does not create a second authentication system.

## HLCE live accumulation / source coverage
The repository already contained the APEX 66.0 canonical active-level registry, APEX 66.1 live publication, APEX 66.1.1 lifecycle reconciliation, and APEX 66.1.2 dynamic level identity stabilization. Scanner heartbeat already exposes `hlce_counts`, collector state, interaction diagnostics, and active-level publisher state.

The missing observability was family-level source coverage. `engine/evidence_accumulation_observatory.py` now adds `level_source_coverage` to `GET /api/learning/evidence-readiness` for the current New York session.

Families reported:
- EXPECTED_MOVE
- GAMMA
- VOLUME_PROFILE
- PRIOR_SESSION
- OVERNIGHT
- OPENING_RANGE
- AUCTION
- OTHER_CANONICAL

Each family reports evidence-backed lifecycle values for:
- registered
- active
- touched
- crossed
- rejected
- accepted
- broken
- reclaimed
- graded
- pending
- stale
- unavailable

No levels, touches, interactions, outcomes, or probabilities are fabricated. `unavailable=true` means no active level in that family reached HLCE for the session.

## Release identity reconciliation
Canonical release identity is now:
- APEX version: `66.2.0`
- build name: `Execution Integrity & Level-Source Coverage`
- release series: `APEX 66`
- release date: `2026-08-08`

Updated canonical identity surfaces:
- `config/apex_release_manifest.json`
- `engine/version.py`
- `config/apex_capability_registry.yaml`
- version regression test

Component versions such as APEX 66.1.2 dynamic-level identity and older engine-local versions remain intact because they identify component implementations rather than the product release.

## Database migration notes
No destructive or additive schema migration is required by APEX 66.2.0.

The level-source coverage diagnostic reads the existing HLCE tables in read-only mode. Execution-boundary management preview state is in-process and does not modify broker/order persistence schemas.

## API changes
No existing API route was removed or renamed.

Enhanced response:
- `GET /api/learning/evidence-readiness` now includes `level_source_coverage`.

Existing Phase 10 endpoints preserve their API contract but now submit through the canonical execution boundary.

## Files added
- `.gitignore`
- `tests/test_apex_66_2_level_source_coverage.py`
- `APEX_66_2_0_IMPLEMENTATION_REPORT.md`
- `APEX_66_2_0_DEPLOYMENT_ROLLBACK.md`

## Files modified
- `app.py`
- `engine/execution/canonical_execution.py`
- `engine/evidence_accumulation_observatory.py`
- `engine/version.py`
- `config/apex_release_manifest.json`
- `config/apex_capability_registry.yaml`
- `tests/test_apex_65_7_integrity.py`
- `tests/test_apex_48_2_version.py`

## Files deprecated
None.

## Files removed
None. No deletion was justified in this consolidation build.

## Validation
Targeted production-integrity regression suite:
- 93 passed
- 0 failed
- 1 skipped

Skipped test:
- Flask route-registration test in `test_apex_65_8_evidence_accumulation.py`; Flask is not installed in the isolated build runtime.

Python compilation:
- `app.py`, `engine/`, `scanner_worker.py`, and `wsgi.py` compiled successfully.

Mutation-surface audit after implementation:
- zero direct `place_order`, `place_complex_order`, `place_change_order`, or `cancel_order` invocations outside `engine/execution/canonical_execution.py` and the broker adapter implementation.

## Validation limitations
- Flask-dependent runtime/API boot tests could not execute because Flask is unavailable in the isolated development runtime. This is an environment limitation, not an application test failure.
- Live Render/E*TRADE broker I/O was not performed from the build environment.
- Live-session HLCE accumulation cannot be proven from a static ZIP. APEX 66.2.0 adds diagnostics specifically to distinguish registry/source absence from collector failure during production RTH.

## Deployment
Deploy the complete repository to the production branch and allow Render to rebuild normally. Preserve all existing production environment variables and durable `/data` storage. Do not delete or replace production learning databases.

After deployment verify:
1. `/api/version` and `/api/release-manifest` report `66.2.0`.
2. `/api/level-calibration/status` shows scanner-owned HLCE collector health.
3. `/api/level-calibration/active-levels/diagnostics` shows canonical registry/HLCE synchronization.
4. `/api/learning/evidence-readiness` contains `level_source_coverage` and reports which institutional families actually reached HLCE.
5. During RTH, confirm expected-move and any available gamma/volume-profile/etc. families progress from registered/active into interactions only when genuine market interaction occurs.

## Recommended next step
Run one live-session acceptance pass focused on level-source coverage and Phase 10 management-order preview/confirmation behavior. If those are clean, begin Decision Reasoning Consolidation by selecting the one authoritative InstitutionalDecision contract and adapting legacy builders rather than creating a new parallel engine.
