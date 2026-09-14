# APEX 69.10.11 Changed Files

1. `engine/historical_payload_archive.py` — new immutable compressed historical payload sidecar, exact round-trip verification, bounded archive plan/apply, capacity guard, and shadow validation.
2. `engine/historical_payload_compaction.py` — readiness ratchet to 69.10.11 archive-foundation state while keeping historical rewrite fail-closed.
3. `engine/storage_retention.py` — exposes archive status and archive-specific guardrails through the existing read-only storage audit.
4. `scripts/apex_storage_maintenance.py` — adds archive plan/status, bounded archive, and shadow-validation operator actions.
5. `engine/configuration_governance.py` — registers the historical payload archive DB configuration variable.
6. `config/apex_release_manifest.json` — 69.10.11 release identity and archive/projection guardrails.
7. `config/apex_capability_registry.yaml` — 69.10.11 capability registration and release identity.
8. `tests/test_apex_69_10_11_immutable_historical_evidence_archive_projection_foundation.py` — archive immutability, round-trip, dry-run, shadow-validation, critical-capacity, CLI, and release tests.
9. `tests/test_apex_69_10_10_historical_payload_dependency_compaction_readiness.py` — current release identity/readiness ratchet.
10. `tests/test_apex_69_10_9_trigger_observatory_retention_evidence_payload_governance.py` — current release identity ratchet.
11. `tests/test_apex_69_10_8_storage_retention_capacity_governance_closure.py` — current release identity ratchet.
12. `tests/test_apex_69_10_7_scanner_completion_truth_live_health_state_closure.py` — current release identity ratchet.
13. `tests/test_apex_69_10_6_decision_time_replay_frame_availability_closure.py` — current release identity ratchet.
14. `tests/test_apex_69_10_5_canonical_flow_sample_identity_excursion_capture_closure.py` — current release identity ratchet.
15. `APEX_69_10_11_IMMUTABLE_HISTORICAL_EVIDENCE_ARCHIVE_PROJECTION_FOUNDATION.md` — implementation and operator guardrail documentation.
16. `APEX_69_10_11_BUILD_REPORT.md` — validation report.
17. `APEX_69_10_11_CHANGED_FILES.md` — changed-files inventory.
