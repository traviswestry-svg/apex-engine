# APEX 69.10.1 Build Report

**Release:** 69.10.1  
**Build:** Scanner Lifecycle & Flow Excursion Capture Closure  
**Baseline:** reconstructed canonical APEX 69.10.0 repository (authoritative repository ZIP plus the delivered 69.10.0 changed-files overlay)

## Findings
The 69.10.0 production scanner was actually running in the dedicated scanner process. Its heartbeat reported `scanner_started=true`, `thread_alive=true`, `phase=RUNNING`, and a valid `last_scan_at`. The web `/health` endpoint nevertheless passed its own process-local `SCANNER_STARTED=false` into health-state resolution and returned `DEGRADED / NOT_STARTED`. This was a cross-process observability defect, not a scanner-start failure.

The flow-learning stores were initialized, but the persisted excursion audit showed zero attempts. Existing forward capture code already preserves the correct identity boundary, so the build does not create a replacement capture engine. Instead it adds scanner-owned lifecycle telemetry around the existing production flow P/L → sealed feature writer → canonical sample excursion path, making every zero-attempt state explicit.

## Implementation
- Added pure cross-process scanner runtime resolver (`engine/scanner_runtime_truth.py`).
- `/health` and APEX 65 runtime-health now prefer a fresh scanner-process heartbeat for scanner started/thread-alive/last-scan truth.
- Stale or missing heartbeats still fail closed.
- Added `scanner_state_source` observability.
- Added `flow_learning_runtime` scanner telemetry with cycle, pipeline, writer, and excursion-capture counters and explicit skip states.
- Preserved feature-writer-owned `defer_excursion_capture=False` canonical capture.
- Refused coarse historical cluster-envelope backfill because it can contain pre-decision observations.
- Advanced current-release capture/version surfaces to 69.10.1.
- Updated release manifest and capability registry.

## Governance
`execution_authority=false`, `behavioral_authority=false`, `automatic_calibration_activation=false`. No broker mutation, synthetic evidence, threshold mutation, duplicate database, duplicate clustering engine, or duplicate outcome/calibration system was introduced.

## Exact tests
Focused regression suite: **73 passed in 2.18s**.

Included:
- `tests/test_apex_69_10_1_scanner_lifecycle_flow_excursion_closure.py`
- `tests/test_apex_69_9_9_live_flow_canonical_excursion_invocation_closure.py`
- `tests/test_apex_69_9_8_live_actionability_capture_probe.py`
- `tests/test_consolidation_guard.py`
- `tests/test_apex_69_10_0_flow_surprise_gamma_transition.py`
- `tests/test_apex_65_7_integrity.py`
- `tests/test_apex_69_0_2_flow_settlement_scheduler_closure.py`
- `tests/test_apex_69_3_canonical_excursion_capture_learning_activation.py`
- `tests/test_apex_69_4_3_live_flow_excursion_invocation_closure.py`

Full `pytest -q` attempt: collection blocked with **68 errors** because `flask` is not installed in the sandbox. Representative root cause: `ModuleNotFoundError: No module named 'flask'`. No claim is made that the complete repository suite passed.

## Remaining limitations
- The existing 88 historical pending excursion labels are intentionally not synthesized or backfilled from coarse session-level cluster envelopes.
- Live flow capture can only advance when genuine source clusters and markable P/L observations exist; 69.10.1 makes absence/skip reasons explicit rather than manufacturing activity.
- Post-deployment verification is required to observe the new heartbeat fields under the production provider/data environment.
