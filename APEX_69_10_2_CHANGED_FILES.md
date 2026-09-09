# APEX 69.10.2 — Changed/New Files

1. `engine/flow_tape.py` — QuantData epoch-millisecond `tradeTime` normalization, current trade-side vocabulary support, normalization diagnostics, and fail-closed invalid-time handling.
2. `engine/flow_classifier.py` — current `ASK` / `BID` / `MID_MARKET` execution-side vocabulary with legacy alias compatibility.
3. `engine/flow_pl_pipeline.py` — canonical source-cluster stage diagnostics and explicit zero-cluster reason attribution.
4. `app.py` — scanner-owned flow-learning stage counters/state attribution and current QuantData side vocabulary in the independent order-flow layer.
5. `engine/feature_store_writer.py` — current-release version truth only; capture behavior unchanged.
6. `engine/historical_evidence_lifecycle.py` — current-release version truth only; evidence behavior unchanged.
7. `engine/trigger_observatory.py` — current-release version truth only; observatory behavior unchanged.
8. `engine/scanner_runtime_truth.py` — current-release version truth only; lifecycle behavior unchanged.
9. `config/apex_release_manifest.json` — 69.10.2 identity and guardrails.
10. `config/apex_capability_registry.yaml` — 69.10.2 release truth and canonical live-flow cluster closure capability.
11. `tests/test_apex_69_10_2_canonical_live_flow_cluster_production_closure.py` — provider-contract, no-synthetic-time, cluster-production, telemetry, and guardrail regression coverage.
12. `tests/test_apex_69_10_1_scanner_lifecycle_flow_excursion_closure.py` — release-ratchet truth only.
13. `tests/test_apex_69_9_9_live_flow_canonical_excursion_invocation_closure.py` — release-ratchet truth only.
14. `tests/test_apex_69_9_8_live_actionability_capture_probe.py` — release-ratchet truth only.
15. `APEX_69_10_2_CANONICAL_LIVE_FLOW_CLUSTER_PRODUCTION_CLOSURE.md` — design/closure documentation.
16. `APEX_69_10_2_BUILD_REPORT.md` — build report.
17. `APEX_69_10_2_CHANGED_FILES.md` — this file.
