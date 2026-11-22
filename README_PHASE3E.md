# APEX Phase 3E — Production Activation Readiness (Research / NO_GO)

This cumulative patch extends the Phase 3D research patch. **No production activation mechanism is included.** It is deliberately impossible for this research assessor to emit a production GO until an independently verified operational authority, external collector, protected signing service, and durable off-host checkpoints are implemented and audited in a future revision.

## Files added

- `engine/forward_provenance_readiness.py`: five-gate evidence inventory and machine-readable fail-closed readiness verdict.
- `scripts/apex_forward_phase3e_readiness.py`: read-only JSON CLI (exit code 2 = not ready).
- `tests/test_forward_provenance_phase3e.py`: operator-assertion escalation and missing-evidence regression tests.

## Five gates

1. Code integrity: deployment SHA, source SHA, tests.
2. Infrastructure: independently observed collector, protected signer, durable off-host checkpoint store, key custody, revocation.
3. Runtime: deployment/boot observations, checkpoint, exact receipt correlation.
4. Resilience: restart recovery, checkpoint continuity, outage policy, monitoring.
5. Safety isolation: trading-unchanged proof, historical read-only proof, fail-closed behavior, rollback plan.

Each evidence reference is merely **operator supplied**. A filled manifest does not authenticate anything and cannot produce a GO. The infrastructure gate always returns `NO_GO`, even when all references are supplied; the other gates return `INSUFFICIENT_EVIDENCE` when evidence is missing and `NO_GO` if the references are supplied but cannot be independently authenticated. `overall_verdict` remains `NO_GO`, `promotion_authority` remains `NONE` and `production_activation_authorized` is always `false` in this implementation.

The current Phase 3C authority signs operator-supplied facts in *synthetic staging*; this is not independent attestation. The Phase 3D reporter deliberately cannot output real-world VERIFIED status. Therefore real-world production GO cannot be grounded by these components. A future production-ready design requires trusted external collection and independent verification, not simply removal of this guard.

## Commands, in isolated checkout

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase3e_readiness
PYTHONPATH=. python -m unittest tests.test_forward_provenance_phase3e -v
PYTHONPATH=. python -m unittest \
  tests.test_forward_provenance tests.test_forward_provenance_verifier \
  tests.test_forward_provenance_phase3a tests.test_forward_provenance_phase3b \
  tests.test_forward_provenance_phase3c tests.test_forward_provenance_phase3d \
  tests.test_forward_provenance_phase3e -v
PYTHONPATH=. python -m unittest discover -s tests \
  -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -v
```

Optional `--evidence /path/to/operator-references.json` and `--operational-report /path/to/existing/phase3d-report.json` arguments read pre-existing files; no new evidence is generated or modified. Sample evidence reference shape: `{"code_integrity":{"deployment_sha":{"reference":"..."}}}`. Paths should be outside production storage; do not supply signing private keys.

**Interpretation:** this is a readiness audit and blocker register, **not** a completed Phase 3E production authorization. Do not enable `APEX_FORWARD_PROVENANCE_ENABLED` on live production from this result. The existing 3,569 decisions remain excluded from retrospective producer authentication and promotion. Keep `BLOCKED_RESEARCH_ONLY`.
