# APEX forward provenance — Phase 2: independent corroboration (research)

## Artifacts

This is a **cumulative patch**: includes Phase 1 instrumented source files and adds:
- `engine/forward_provenance_verifier.py`: verifies a receipt chain and externally signed DEPLOY, BOOT, CHECKPOINT statements with a pinned Ed25519 public key.
- `scripts/verify_forward_provenance.py`: read-only, offline CLI.
- `tests/test_forward_provenance_verifier.py`: isolated positive and fail-closed tests.

No APEX production deployment is performed. No existing historical evidence is rewritten. No proof is fabricated by this package.

## Critical trust distinction

A runtime `RENDER_GIT_COMMIT` value is **self-reported**. An Ed25519 signature proves that an issuer signed a statement, **not** that the issuer independently verified its assertions. An external collector must independently authenticate the deployment SHA, service ID, boot identity, PID, and the event time interval. The collector's *pinned* verification key must be controlled outside the APEX process. Do not allow APEX to sign its own claims with the attestation key.

An externally anchored checkpoint must be stored **off-host and outside the forward provenance sidecar**. The verifier requires that its signed `sequence` and `head_hash` match the full current ledger; thus older checkpoints are intentionally rejected after new events are appended. Capture a current checkpoint when auditing a static ledger copy.

This implementation **does not** authenticate provider market-data timestamps, the source database row contents, the external collector's truthfulness, or historical decisions. A successful result is `EXTERNALLY_CORROBORATED_RECEIPTS`, *not* `AUTHENTICATED_PRODUCER` or permission to promote evidence. The verifier is standalone; there is **no promotion gate integrated into production decision or learning paths**.

## Attestation contract

Each statement is JSON with exactly `{ "body": {...}, "signature": "base64-Ed25519-signature" }`. Signature is over compact canonical JSON with keys sorted, no whitespace, ASCII-escaped text, matching `engine.forward_provenance._canonical(body)`.

Each body contains:
- `domain`: `APEX_FORWARD_PROVENANCE_ATTESTATION_V1`
- `schema`: `1`
- `kind`: one of `DEPLOY`, `BOOT`, `CHECKPOINT`
- `ledger_id`: identifier independently assigned to the particular ledger capture
- `service_id`: independently observed deployment service identity

`DEPLOY` also contains `git_sha` (full 40-hex Git SHA), `release`, `valid_from`, and `valid_until`.

`BOOT` also contains `git_sha`, `release`, `boot_id`, `pid` (JSON integer), `valid_from`, and `valid_until`.

`CHECKPOINT` also contains `sequence` (event count), `head_hash` (hex), and `captured_at` (signed UTC timestamp). Times must be offset-aware ISO-8601. Three statements must be signed by a trusted issuer whose Ed25519 public key is pinned in the independent audit environment. The verifier is intentionally strict on cardinality, digest, commit, boot, PID, service and time-window consistency.

### Run in an independent offline environment

Prerequisite: `cryptography` Python package; a read-only copy of the sidecar ledger (including committed WAL data); independently signed attestation files; a pinned 32-byte Ed25519 public key. In the repo root:

```bash
PYTHONPATH=. python scripts/verify_forward_provenance.py \
  --ledger /audit-copy/apex_forward_provenance.db \
  --decision-id DECISION_ID \
  --statements /independent-store/attestations.json \
  --pinned-public-key /independent-store/pinned_public_key.bin
```

Failure exits with code 2. The CLI writes only its result to stdout. **Never substitute files produced by the running APEX process for independent attestations.**

## Validation performed

```bash
PYTHONPATH=. python -m unittest tests.test_forward_provenance tests.test_forward_provenance_verifier -v
PYTHONPATH=. python -m unittest discover -s tests -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -v
```

No staging integration with real deployment attestations, no external off-host signing service, no long-running scanner rehearsal, and no production verification has been performed.

## Required follow-up

1. Select an independent trusted attestation service and pinned verification keys, with rotation and revocation policy.
2. Make that service derive Render deployment commit/rollout intervals independently (not from APEX env variables alone), and derive boot/PID evidence independently where feasible.
3. Publish signed chain-head checkpoints to WORM or equivalent independent storage; preserve checkpoint capture history.
4. Verify real staging receipts from a copied ledger, including restart and failure cases; use time-of-check / WAL snapshot handling.
5. Only after a separate source-row authenticity and authorization design review, consider a read-only candidate eligibility report. Do **not** enable evidence promotion as a side effect of this patch.
