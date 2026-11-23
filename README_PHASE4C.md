# APEX Phase 4C — Durable Replay & Checkpoint Continuity (Research)

**State: ISOLATED STAGING ONLY / NO_GO.** This patch simulates a remote authority's persistent state using a **local disposable SQLite database**. It is not hosted off the APEX system, cannot prove its own independence, and is **not** tamper-proof against a database administrator. No production trust boundary is established. Phase 4C's *staging algorithm* is built and tested; real off-host storage is **not yet integrated**.

## Code files

- `engine/forward_provenance_checkpoint_store.py`: staged atomic nonce register (`BEGIN IMMEDIATE`, uniqueness), append-only checkpoint table, head compare-and-swap in one transaction, canonical SHA-256 chain, SQL no-update/no-delete triggers, read-only chain audit with optional caller-supplied expected head.
- `tests/test_forward_provenance_phase4c.py`: 15 synthetic persistence, concurrency, restart, replay, tamper, false-claim, continuity, and rejection tests.
- `scripts/apex_forward_phase4c_staging.py`: isolated disposable test CLI returning JSON with explicit `NO_GO` and `LOCAL_SQLITE_OFF_HOST_SIMULATION_NOT_INDEPENDENT`.

## Safe steps in an isolated checkout

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase4c_staging --json
PYTHONPATH=. python -m unittest tests.test_forward_provenance_phase4c -v
PYTHONPATH=. python -m unittest \
  tests.test_forward_provenance tests.test_forward_provenance_verifier \
  tests.test_forward_provenance_phase3a tests.test_forward_provenance_phase3b \
  tests.test_forward_provenance_phase3c tests.test_forward_provenance_phase3d \
  tests.test_forward_provenance_phase3e tests.test_forward_provenance_phase4a \
  tests.test_forward_provenance_phase4b tests.test_forward_provenance_phase4c -q
PYTHONPATH=. python -m unittest discover -s tests \
  -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -q
```

The first command runs only 15 Phase 4C tests and uses temporary directories. It does not contact Render APIs, create a real external store, read production databases, use KMS, or authorize any production behavior. Do not enable `APEX_FORWARD_PROVENANCE_ENABLED` or install signing keys or live Render tokens in the APEX service.

## Semantics

1. **Nonce reservation**: Once committed, a nonce remains reserved across a local restart. If signing crashes before publishing a checkpoint, the reservation is an outstanding gap—not evidence of a completed attestation. It must never be automatically reused. Uniqueness and SQLite's exclusive write lock decide the single winner among competing writers.
2. **Checkpoint publication**: Requires a Phase 4B staging attestation that passes the existing signature/claim verifier, a matching previously reserved nonce, and an exact predecessor head. The entire append and head comparison occur in one transaction. Duplicates and stale heads fail closed.
3. **Auditing**: Walks the checkpoint sequence and compares every hash to a canonical record. The optional `expected_anchor` detects rollback relative to a *caller-provided* head; it does not authenticate that anchor. SQLite triggers deter accidental edits only; privileged administrators can drop them, replace the entire database, or roll back all files.
4. **Crash handling**: Incomplete reservations remain visible as `uncheckpointed_reservations`. There is no algorithm to fabricate a missing signed attestation. Independent operator investigation is required.
5. **Historical isolation**: Phase 4C never imports the 3,569 historical decisions. It has no trading/order integration and never returns `VERIFIED` or `GO`.

## Additional requirements for real off-host infrastructure

- Provision a **separately administered account/service**, outside APEX's deployment, filesystem, and administrative credentials.
- Use an external transactional database for persistent uniqueness and head CAS, with strict service IAM and independent backups, **plus immutable external anchor storage** (e.g. correctly configured provider-enforced write-once retention, versioning, retention lock, and independent retention policies). A SQLite DB merely placed on a different host does not make records immutable.
- Implement authenticated issuance/retrieval of checkpoint attestations, independently pinned keys, protected KMS/HSM signing, key rotation/revocation, and robust multi-writer reconciliation with verified external anchors.
- End-to-end test actual network disconnects, concurrent writers, process crashes, expired/compromised credentials, missing checkpoints, storage outages, WORM retention, and verified rollback detection.
- Establish process-origin evidence independently; Render deployment metadata alone cannot authenticate scanner boot/PID.
- Integrate real collected evidence into the Phase 3E five-gate readiness auditor, with independent verification. Until then activation remains `NO_GO`.

**Production activation is not authorized. Promotion authority: NONE. Historical 3,569 population: EXCLUDED.**
