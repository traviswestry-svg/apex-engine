# APEX 69.10.6 Build Report

**Build:** Decision-Time Replay Frame Availability & Canonical Feature Persistence Closure  
**Baseline reconstructed:** APEX 69.10.5 from the authoritative 69.10.4 repository ZIP plus the delivered 69.10.5 changed-files overlay.  
**Release type:** additive patch / observational-learning pipeline closure.

## Repository audit finding

The live 69.10.5 telemetry showed the feature writer was invoked successfully, source clusters were available, and the canonical identity counters were clean, but no feature rows could be persisted because every sealed candidate was point-in-time gated for lack of an eligible SPX replay frame.

Repository inspection confirmed the generic replay recorder is reached from the normal per-ticker scanner analysis path, while the core scanner universe does not include SPX. The separate scanner-owned live active-level publisher already refreshes SPX every minute using the exact provider paths needed to form honest point-in-time learning context.

## Implementation

- Added a pure bounded `build_learning_replay_snapshot()` adapter in `engine/live_active_level_publisher.py`.
- Reused the publisher's already-fetched SPX flow, volume-profile and canonical market-state subset.
- Published forward-only SPX replay frames through the existing app replay recorder.
- Added fail-closed states when the replay recorder or observed context is unavailable.
- Added replay availability diagnostics to both live active-level publisher telemetry and flow-learning runtime telemetry.
- Kept `engine/feature_store_writer.py` unchanged so the existing no-future / max-staleness guard remains the canonical join authority.
- Updated release manifest and Capability Registry to 69.10.6.

## Validation

Focused closure / regression suite:

- `tests/test_apex_69_10_6_decision_time_replay_frame_availability_closure.py`
- `tests/test_apex_69_10_5_canonical_flow_sample_identity_excursion_capture_closure.py`
- `tests/test_apex_66_1_live_active_level_publication.py`
- `tests/test_consolidation_guard.py`

Result: **27 passed**.

Broader APEX 69.10.x + feature-store regression suite result: **163 passed**.

Python compilation: **723 files compiled, 0 errors**.

Architecture integrity snapshot:

- status: **HEALTHY**
- identity aligned: **true**
- release version: **69.10.6**
- registry version: **69.10.6**
- capability count: **58**

The full Flask-dependent suite was not collected because Flask is not installed in this sandbox. No claim is made that the entire repository suite passed.

## Production authority

- Decision authority: unchanged.
- Execution authority: unchanged.
- Production effect: observational learning only.
- Automatic calibration activation: unchanged.
- Replay staleness tolerance: unchanged.
- Historical evidence: not rewritten.
