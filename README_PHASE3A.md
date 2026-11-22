# APEX Forward Provenance — Phase 3A: Isolated Synthetic Staging Integration

## Scope and trust boundary

This is a **cumulative Phase 1 + Phase 2 + Phase 3A research patch**, based on the November 21 APEX source. The new Phase 3A harness uses Python `tempfile.TemporaryDirectory`, a disposable SQLite receipt ledger, and a SQLite-API backup audit copy. It does **not** open `/data`, existing decision stores, real QuantData, or a trading broker. No production environment setting or existing historical row is modified.

**Critical:** The Ed25519 signing key in this harness is generated inside the test process. The passing positive case establishes only simulated signature and receipt consistency. It is **not independent attestation** and cannot prove the original producer process or support promotion. A real independent attestations service is Phase 3C.

## Included files

- `engine/forward_provenance.py` — Phase 1 runtime-claimed append-only receipts.
- `engine/forward_provenance_verifier.py` — Phase 2 signed-statement consistency verifier.
- `scripts/verify_forward_provenance.py` — Phase 2 read-only verifier CLI.
- **`scripts/apex_forward_phase3a_staging.py`** — new isolated end-to-end synthetic staging harness.
- `tests/test_forward_provenance.py`, `tests/test_forward_provenance_verifier.py` — existing tests.
- **`tests/test_forward_provenance_phase3a.py`** — new isolated/CLI regression tests.
- `app.py`, `engine/gamma_transition.py`, `engine/evidence_pipeline.py` — cumulative Phase 1 instrumented source. Do **not** deploy without comparing against current main.

## Run from APEX repository root

No production env changes required. Existing `APEX_FORWARD_PROVENANCE_ENABLED` is overridden locally only for the child test scope, and the ledger path is patched to a new temporary file.

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase3a_staging --json
PYTHONPATH=. python -m unittest tests.test_forward_provenance tests.test_forward_provenance_verifier tests.test_forward_provenance_phase3a -v
PYTHONPATH=. python -m unittest discover -s tests -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -v
```

The harness prints `NOT_REAL_WORLD_AUTHENTICATION` and `promotion_authority: NONE`. It returns exit code 2 when a check fails. No audit artifacts or keys survive the temporary-directory cleanup.

## Checks

1. Synthetic calculation → persisted gamma → persisted decision produces three ordered receipts and a verified local SHA-256 chain.
2. `inserted=False` duplicate writes do not append receipts.
3. A transaction-consistent SQLite backup produces a readable audit copy (including committed WAL data).
4. A **test-only** signed DEPLOY/BOOT/CHECKPOINT triplet passes structural and signature consistency verification, but has no independent authority.
5. Missing decision fails closed.
6. Missing checkpoint fails closed.
7. Untrusted signing key fails closed.
8. A re-signed mismatched boot ID fails closed.
9. Missing gamma receipt fails closed.
10. An old signed checkpoint fails against a newer copied ledger.
11. SQLite append-only UPDATE guard fires.
12. Disabled mode does not create a ledger.

## Local validation

- 2 new Phase 3A tests passed.
- 12 existing Phase 1/2 tests passed.
- 24 existing gamma receipt regression tests passed.
- 12/12 synthetic harness checks passed.
- Existing Phase 2 tests may emit a Python 3.13 `ResourceWarning` for a database connection; tests still pass. Address separately in code hygiene review.

## Not covered / required next

- Phase 3B: true child-process restart and PID/boot rollover, fault injection around commits, and recovery semantics.
- Phase 3C: externally operated signer and durable off-host WORM checkpoint publication.
- Phase 3D: read-only verifier against actual staging receipts and external evidence.
- Phase 3E: operational authorization and production readiness review.

There is **no evidence promotion**, no brokerage activation, no reclassification of the existing 3,569 decisions, and no direct production deployment authority in this package.
