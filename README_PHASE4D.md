# APEX Phase 4D — Independent-Evidence Correlation Verifier (Research)

**State: LOCAL RESEARCH VALIDATED — REAL-WORLD AUTHENTICATION NOT ESTABLISHED — `NO_GO`.**

## Scope

This build validates the correlations between (1) a Phase 4A Render deployment-observation envelope, (2) a Phase 4B restricted signer attestation, (3) a Phase 4C transactionally consistent checkpoint copy and (4) a separately pinned **synthetic** Ed25519 checkpoint-anchor signature. It does **not** provision or operate an independent Render observer, managed key custody, remote immutable checkpoint store, or authenticated scanner-process supervisor.

A correctly signed deployment receipt **does not prove who generated a gamma calculation**. The Phase 4A–4C chain deliberately has no authenticated `boot_id`/PID. Passing all checks therefore results in `STAGING_CORROBORATED_NO_PROCESS_ATTESTATION`, never `VERIFIED`. Production activation and promotion authority remain disabled.

## Files

- `engine/forward_provenance_realworld_verifier.py`: strict read-only correlation and independent-anchor-signature checks, trust pinning, revocation/expiry, checkpoint continuity and exact attestation digest, and fail-closed process identity boundary. No database initialization or writes.
- `scripts/apex_forward_phase4d_staging.py`: isolated test harness with synthetic ephemeral keys and disposable SQLite evidence.
- `scripts/apex_forward_phase4d_verify.py`: read-only JSON evidence bundle verifier; **always exits code 2** because no real-world activation authority exists.
- `tests/test_forward_provenance_phase4d.py`: 14 targeted validations.

This is a cumulative patch: overlay its `apex-engine-main/...` files on the same source revision already deployed. Do not run tests directly from the patch ZIP alone; base repository modules are also necessary.

## Render Shell tests (safe; synthetic)

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase4d_staging --json
PYTHONPATH=. python -m unittest tests.test_forward_provenance_phase4d -v
PYTHONPATH=. python -m unittest \
  tests.test_forward_provenance tests.test_forward_provenance_verifier \
  tests.test_forward_provenance_phase3a tests.test_forward_provenance_phase3b \
  tests.test_forward_provenance_phase3c tests.test_forward_provenance_phase3d \
  tests.test_forward_provenance_phase3e tests.test_forward_provenance_phase4a \
  tests.test_forward_provenance_phase4b tests.test_forward_provenance_phase4c \
  tests.test_forward_provenance_phase4d -q
PYTHONPATH=. python -m unittest discover -s tests \
  -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -q
```

Expected staging report: `checks_passed: 14`, `checks_total: 14`, `ok: true`, `verdict: NO_GO`, `independent_collector: NOT_DEPLOYED`, `runtime_process_authentication: NOT_ESTABLISHED`.

## Optional offline evidence verification

Supply a JSON `bundle.json` containing only `observer_envelope`, `signer_attestation`, and `signed_anchor` (the exact Phase 4B / 4D envelope shapes), an independently reviewed *public-key-only* `trust_policy.json`, and a **disposable** checkpoint database copy. Never use production databases directly or pass private signing keys. The trust policy must have `environment: ISOLATED_STAGING` and three distinct public-key roles (`collector`, `signer`, `anchor`).

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase4d_verify \
  --bundle /tmp/staging/bundle.json \
  --trust-policy /tmp/staging/trust_policy.json \
  --checkpoint-copy /tmp/staging/checkpoints.db
```

The verifier returns `NO_GO` and exit code **2** even on a fully consistent staging chain. There is intentionally no `--production`, `--promote`, `--approve`, or `--enable` option.

## Threat boundaries / blockers

1. **Collector**: APEX still lacks a separately deployed collector with independently controlled, limited-scope Render API credentials and independent evidence retention. Source code running in the APEX shell is *not* an independent collector.
2. **Signer**: Staging test keys are injected and local; protected remote KMS/HSM key custody and separation of duties are not deployed.
3. **Checkpoint store**: Phase 4C is a local SQLite algorithm; external WORM/retention-lock storage and independently pinned durable anchors have not been established. A signature from an operator-supplied key is not evidence of independent custody.
4. **Process**: No externally supervised and authenticated scanner startup/boot/PID or secure source-to-process linkage is available. Never promote source runtime claims to authenticated facts.
5. **Safety**: Production `APEX_FORWARD_PROVENANCE_ENABLED` remains unset/off. No changes to paper/live routing, scanner scoring, or the 3,569 historical decisions. Historical classification remains `BLOCKED_RESEARCH_ONLY`.

**Implementation coverage**: deterministic local evidence checking, rejection tests, no database writes. **Not implemented**: real-world provider observation, process supervision, external durable authority, and production activation authorization. These remain `NO_GO` blockers before Phase 4E.
