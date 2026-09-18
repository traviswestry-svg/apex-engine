# APEX 69.10.14 — Changed Files Manifest

Build: **Canonical Gamma Evidence Identity & Decision-Time Provenance**

This delivery contains **only files modified or created by APEX 69.10.14**. Repository-relative paths are preserved. No unchanged repository files are included.

## Files

- **NEW** `APEX_69_10_14_BUILD_REPORT.md` — Required audit, implementation, validation, storage, API, calibration, and deployment report.
- **NEW** `APEX_69_10_14_CANONICAL_GAMMA_EVIDENCE_IDENTITY_DECISION_TIME_PROVENANCE.md` — Architecture and operational documentation for the release.
- **NEW** `APEX_69_10_14_CHANGED_FILES.md` — Authoritative changed-file delivery manifest.
- **MODIFIED** `APEX_ENVIRONMENT_VARIABLE_REFERENCE.md` — Documents generic and QuantData-specific gamma freshness/continuity thresholds.
- **MODIFIED** `app.py` — Propagates canonical gamma decision-time capture into canonical runtime output.
- **MODIFIED** `config/apex_capability_registry.yaml` — Registers the canonical gamma provenance capability and existing API surfaces.
- **MODIFIED** `config/apex_release_manifest.json` — Ratchets canonical release to 69.10.14, schema version 6, and gamma provenance guardrails.
- **MODIFIED** `engine/configuration_governance.py` — Registers governed gamma freshness/cadence environment variables.
- **MODIFIED** `engine/evidence_eligibility.py` — Extends the existing dealer evidence gate with canonical gamma integrity states.
- **MODIFIED** `engine/evidence_pipeline.py` — Persists canonical gamma decision linkage and readiness counts.
- **MODIFIED** `engine/gamma_transition.py` — Implements canonical gamma identity, deduplication, freshness, continuity, provenance, metrics, and exact lookup.
- **MODIFIED** `engine/historical_evidence_lifecycle.py` — Freezes exact decision-time gamma evidence and matching decision-time capacity context.
- **MODIFIED** `engine/outcome_grader.py` — Carries only frozen decision-time gamma provenance into grading; no latest-gamma lookup.
- **MODIFIED** `engine/trigger_observatory.py` — Adds canonical gamma linkage to trigger persistence/history/trade view.
- **MODIFIED** `tests/test_apex_69_10_10_historical_payload_dependency_compaction_readiness.py` — Updates the historical release-ratchet expectation to the current canonical 69.10.14 release while preserving that release’s own historical capability assertions.
- **MODIFIED** `tests/test_apex_69_10_11_immutable_historical_evidence_archive_projection_foundation.py` — Updates the historical release-ratchet expectation to the current canonical 69.10.14 release while preserving that release’s own historical capability assertions.
- **MODIFIED** `tests/test_apex_69_10_12_scanner_process_authority_cross_process_health_truth_closure.py` — Updates the historical release-ratchet expectation to the current canonical 69.10.14 release while preserving that release’s own historical capability assertions.
- **MODIFIED** `tests/test_apex_69_10_13_historical_payload_archive_pagination_complete_shadow_validation_closure.py` — Updates the historical release-ratchet expectation to the current canonical 69.10.14 release while preserving that release’s own historical capability assertions.
- **NEW** `tests/test_apex_69_10_14_canonical_gamma_evidence_identity_decision_time_provenance.py` — New 69.10.14 regression coverage.
- **MODIFIED** `tests/test_apex_69_10_5_canonical_flow_sample_identity_excursion_capture_closure.py` — Updates the historical release-ratchet expectation to the current canonical 69.10.14 release while preserving that release’s own historical capability assertions.
- **MODIFIED** `tests/test_apex_69_10_6_decision_time_replay_frame_availability_closure.py` — Updates the historical release-ratchet expectation to the current canonical 69.10.14 release while preserving that release’s own historical capability assertions.
- **MODIFIED** `tests/test_apex_69_10_7_scanner_completion_truth_live_health_state_closure.py` — Updates the historical release-ratchet expectation to the current canonical 69.10.14 release while preserving that release’s own historical capability assertions.
- **MODIFIED** `tests/test_apex_69_10_8_storage_retention_capacity_governance_closure.py` — Updates the historical release-ratchet expectation to the current canonical 69.10.14 release while preserving that release’s own historical capability assertions.
- **MODIFIED** `tests/test_apex_69_10_9_trigger_observatory_retention_evidence_payload_governance.py` — Updates the historical release-ratchet expectation to the current canonical 69.10.14 release while preserving that release’s own historical capability assertions.

**Total changed/created files: 24**

## Delivery Rules

- Copy files into the canonical repository using the paths above.
- Do not replace the repository with this package; it is a changed-files-only overlay.
- No database files, test caches, bytecode, or other runtime artifacts are included.
