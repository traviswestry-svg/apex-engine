# APEX 69.10.7 Changed Files

1. `app.py` — explicit full-scan completion telemetry, bounded lock-contention retry, and fail-closed live health truth.
2. `scanner_worker.py` — publishes `scan_completion_runtime` through the canonical dedicated-scanner heartbeat.
3. `engine/scanner_runtime_truth.py` — fresh-heartbeat resolution now exports explicit process full-scan completion timestamp/duration/runtime.
4. `config/apex_release_manifest.json` — release identity and scanner-completion guardrails ratcheted to 69.10.7.
5. `config/apex_capability_registry.yaml` — release identity updated and scanner completion truth capability registered.
6. `tests/test_apex_69_10_1_scanner_lifecycle_flow_excursion_closure.py` — scanner-health wiring assertion ratcheted to the explicit process-completion truth path.
7. `tests/test_apex_69_10_5_canonical_flow_sample_identity_excursion_capture_closure.py` — release identity assertions ratcheted only.
8. `tests/test_apex_69_10_6_decision_time_replay_frame_availability_closure.py` — release identity assertions ratcheted only.
9. `tests/test_apex_69_10_7_scanner_completion_truth_live_health_state_closure.py` — new closure and guardrail tests.
10. `APEX_69_10_7_SCANNER_COMPLETION_TRUTH_LIVE_HEALTH_STATE_CLOSURE.md` — implementation/live-verification contract.
11. `APEX_69_10_7_BUILD_REPORT.md` — audit and validation report.
12. `APEX_69_10_7_CHANGED_FILES.md` — this manifest.
