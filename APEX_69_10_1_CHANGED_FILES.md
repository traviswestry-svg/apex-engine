# APEX 69.10.1 — Changed/New Files

1. `app.py` — cross-process scanner health truth integration; flow-learning lifecycle telemetry.
2. `scanner_worker.py` — publishes scanner-owned `flow_learning_runtime` in heartbeat.
3. `engine/scanner_runtime_truth.py` — new pure cross-process scanner lifecycle resolver.
4. `engine/feature_store_writer.py` — current-release writer version truth 69.10.1.
5. `engine/historical_evidence_lifecycle.py` — current-release capture/version truth 69.10.1.
6. `engine/trigger_observatory.py` — current-release observatory/version truth 69.10.1.
7. `config/apex_release_manifest.json` — 69.10.1 build identity and closure guardrails.
8. `config/apex_capability_registry.yaml` — current canonical version consistency.
9. `tests/test_apex_69_10_1_scanner_lifecycle_flow_excursion_closure.py` — new lifecycle/capture closure tests.
10. `tests/test_apex_69_9_8_live_actionability_capture_probe.py` — release truth ratchet.
11. `tests/test_apex_69_9_9_live_flow_canonical_excursion_invocation_closure.py` — release truth/build-name ratchet.
12. `APEX_69_10_1_SCANNER_LIFECYCLE_FLOW_EXCURSION_CAPTURE_CLOSURE.md` — implementation/release documentation.
13. `APEX_69_10_1_BUILD_REPORT.md` — build and test report.
14. `APEX_69_10_1_CHANGED_FILES.md` — changed/new files manifest.
