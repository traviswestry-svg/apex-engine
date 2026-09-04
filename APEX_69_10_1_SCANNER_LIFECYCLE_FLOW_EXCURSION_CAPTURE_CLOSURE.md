# APEX 69.10.1 — Scanner Lifecycle & Flow Excursion Capture Closure

## Purpose
APEX 69.10.1 is a focused production-lifecycle closure following the 69.10.0 Flow Surprise Intelligence & Gamma Transition Dynamics release. It does not add trading intelligence or alter conviction, consensus, entry thresholds, sizing, execution, or calibration policy.

## Production evidence that triggered the build
The 69.10.0 `/health` payload reported `DEGRADED / Scanner expected during the live session but not started`, while the durable scanner-process heartbeat simultaneously reported `scanner_started=true`, `thread_alive=true`, `phase=RUNNING`, and a real `last_scan_at`. The same heartbeat showed flow learning stores initialized but canonical flow excursion capture at zero attempts.

## Scanner lifecycle closure
Production scanning is normally owned by `scanner_worker.py`, not the Gunicorn/Flask process. The web worker's local `SCANNER_STARTED` flag therefore cannot be authoritative by itself.

69.10.1 adds `engine/scanner_runtime_truth.py`, a deterministic, observational cross-process resolver. A fresh, non-stopped scanner heartbeat may prove that the dedicated scanner is started and its scanner thread is alive. A stale, malformed, missing, or stopped heartbeat never does so. The `/health` route and APEX 65 runtime-health aggregation now use this effective scanner state and may source `last_scan_at` and heartbeat time from the scanner-process heartbeat.

New health field:
- `scanner_state_source`: `SCANNER_PROCESS_HEARTBEAT` or `WEB_PROCESS_LOCAL_STATE`

This corrects the false `DEGRADED / NOT_STARTED` state without weakening stale-heartbeat fail-closed behavior.

## Flow excursion capture closure
The existing canonical architecture is preserved:
- Flow identity remains the existing `flow_clusters` infrastructure.
- Feature identity remains the immutable canonical feature `sample_id`.
- `flow_sample_identity_map` remains the authoritative bridge from sealed cluster lineage to feature identity.
- `flow_sample_excursions` remains the canonical sample-scoped MFE/MAE ledger.
- `feature_store_writer.write_samples(..., defer_excursion_capture=False)` remains the production post-persistence capture boundary.
- No new database, outcome ledger, calibration store, or cluster engine is introduced.

69.10.1 adds explicit scanner-owned lifecycle telemetry for every live flow-learning cycle. The scanner heartbeat now includes `flow_learning_runtime` with cumulative counters and the latest lifecycle state, including:
- `NO_SOURCE_CLUSTERS`
- `SESSION_GATED`
- `UNAVAILABLE`
- `FEATURE_WRITER_DISABLED`
- `FEATURE_WRITER_UNAVAILABLE`
- `FEATURE_SESSION_GATED`
- `WRITER_NO_CAPTURE_TARGET`
- `CAPTURE_ATTEMPTED`
- `ERROR`

Counters include pipeline runs, source clusters, samples recorded, writer invocations, feature rows written, capture attempts, inserted/updated excursions, missing P/L, and capture errors.

This means `capture_attempts=0` can no longer be interpreted as a healthy capture path without context. Production will expose whether no canonical flow clusters existed, the pipeline was unavailable, the session was gated, no sealed feature target existed, or capture actually ran.

## Historical pending vectors
69.10.1 deliberately does **not** backfill the existing historical pending feature vectors from the coarse session-level `flow_pl_cluster_tracking` envelope. That ledger can contain observations that predate an individual sample's decision time. Using it directly to create sample-scoped excursions could leak hindsight.

Historical vectors remain pending unless exact, timestamp-valid, post-decision canonical evidence exists. No synthetic evidence is created.

## Governance
- `execution_authority = false`
- `behavioral_authority = false`
- `automatic_calibration_activation = false`
- no broker authority
- no automatic production threshold mutation
- no synthetic excursion evidence
- no duplicate persistence architecture
- no duplicate outcome/calibration architecture

## Version truth
Canonical version surfaces are advanced from 69.10.0 to 69.10.1, with build name `Scanner Lifecycle & Flow Excursion Capture Closure`.

## Validation
Focused regression command covered the new closure tests plus prior scanner, settlement, excursion-capture, 69.10.0 Flow Surprise/Gamma Transition, and consolidation guards.

Result: **73 passed, 0 failed**.

The complete repository suite was attempted and stopped during collection with **68 collection errors** because the sandbox lacks the `flask` package (`ModuleNotFoundError: No module named 'flask'`). This is an environment/dependency limitation, not represented as a passing full suite.

## Deployment verification expectations
After deployment during `MARKET_OPEN`:
1. `/health.scanner_started` should be true when the fresh dedicated scanner heartbeat reports a running scanner.
2. `/health.scanner_state_source` should report `SCANNER_PROCESS_HEARTBEAT` in dedicated-process production mode.
3. `/health.health_state` should no longer report `DEGRADED` solely because the web worker's local scanner flag is false.
4. `scanner_process.flow_learning_runtime` should explain each flow cycle and why capture attempts are or are not occurring.
5. `scanner_process.flow_excursion_capture.capture_attempts` should increase only when a genuine canonical capture attempt occurs; no values are fabricated to force movement.
