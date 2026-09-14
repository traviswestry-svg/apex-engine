# APEX 69.10.10 Changed Files

1. `engine/historical_payload_compaction.py` — new read-only historical payload dependency and compaction-readiness audit.
2. `engine/storage_retention.py` — exposes bounded historical payload readiness diagnostics through the existing authenticated storage audit.
3. `scripts/apex_storage_maintenance.py` — adds read-only exhaustive `payload-compaction-readiness` operator action and rejects `--apply`.
4. `config/apex_release_manifest.json` — release identity and 69.10.10 compaction-readiness guardrails.
5. `config/apex_capability_registry.yaml` — release identity and new historical payload compaction-readiness capability.
6. `tests/test_apex_69_10_10_historical_payload_dependency_compaction_readiness.py` — 69.10.10 closure tests.
7. `tests/test_apex_69_10_9_trigger_observatory_retention_evidence_payload_governance.py` — current release identity ratchet; 69.10.9 projection contract preserved.
8. `tests/test_apex_69_10_8_storage_retention_capacity_governance_closure.py` — current release identity ratchet.
9. `tests/test_apex_69_10_7_scanner_completion_truth_live_health_state_closure.py` — current release identity ratchet.
10. `tests/test_apex_69_10_6_decision_time_replay_frame_availability_closure.py` — current release identity ratchet.
11. `tests/test_apex_69_10_5_canonical_flow_sample_identity_excursion_capture_closure.py` — current release identity ratchet.
12. `APEX_69_10_10_HISTORICAL_EVIDENCE_PAYLOAD_DEPENDENCY_COMPACTION_READINESS.md` — implementation and guardrail documentation.
13. `APEX_69_10_10_BUILD_REPORT.md` — build/validation report.
14. `APEX_69_10_10_CHANGED_FILES.md` — changed-files inventory.
