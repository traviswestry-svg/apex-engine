# APEX Forward Provenance — Phase 3C: External authority / off-host checkpoints (staging research)

**Delivery:** additive cumulative research patch on Phase 3B. **No real independent authority or off-host infrastructure has been deployed.** All Phase 3C acceptance tests use synthetic operator-supplied deployment/boot records and an ephemeral Ed25519 test key. No historical promotion or execution authority.

## Purpose

The `engine/forward_provenance_external_authority.py` module and `scripts/apex_forward_phase3c_staging.py` rehearsal provide a narrowly scoped **outside-the-APEX-process signing workflow**. They deliberately do NOT add an APEX endpoint, expose a signing key to the scanner, or turn on production provenance.

- `create_staging_bundle`: rejects non-staging contexts, requires operator-supplied **deployment evidence** labeled `RENDER_API_DEPLOY_RECORD` and **supervisor boot evidence** labeled `EXTERNAL_SUPERVISOR_BOOT_RECORD`, requires matching service/ledger/release/SHA, and signs three statements (DEPLOY, BOOT, CHECKPOINT) over an audited SQLite copy.
- `read_ledger_head`: checks hash-chain integrity of a transaction-consistent audit copy, not the live source database. It does not certify that the copy was independently obtained or that the source database is complete before the first checkpoint.
- `export_bundle_atomic`: creates a write-once checkpoint file with `O_EXCL`, flushes and syncs file and directory; this is **not** an immutable remote/WORM store.
- `verify_staging_bundle`: uses an externally supplied pinned public key and separate local trust policy, checks revocations, signatures, identity, ledger hash-chain, checkpoint head/length and per-decision receipt. It marks success `STAGING_CORROBORATED_OPERATOR_FACTS`, explicitly **not real-world deployment authentication**. No migration/trade authority.
- Prior checkpoint hash chaining is reserved for the next implementation: successor checkpoints are **rejected** until the complete signed predecessor trail and key transition rules are supported. This prevents accidentally treating an unverified `previous_checkpoint_sha256` as proof of continuity.

**Critical trust boundary:** the code verifies that an operator-supplied `evidence_source` string has the right type; it does **not** query Render's API or an independent process supervisor or establish that the purported observations were true. It must not be represented as independent production attestation. Operational integration requires a separately managed collector that obtains authenticated facts from Render and an out-of-process supervisor and retains authentic responses. The private key must never enter APEX containers or be committed to Git.

## Run — safe in an existing checkout with patch applied

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase3c_staging --json
PYTHONPATH=. python -m unittest \
  tests.test_forward_provenance tests.test_forward_provenance_verifier \
  tests.test_forward_provenance_phase3a tests.test_forward_provenance_phase3b \
  tests.test_forward_provenance_phase3c -v
PYTHONPATH=. python -m unittest discover -s tests \
  -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -v
```

These commands create only **temporary synthetic** data in the local testing filesystem. They do not interact with `/data`, production decisions, real Render API credentials, private persistent keys or a live network. The staging harness restores monkeypatched functions on exit.

## Local test results

- Phase 3C simulation: **15 / 15** synthetic checks passed.
- Phase 1–3C forward-provenance tests: **18 / 18** passed.
- Existing Stage 3B.3.15 gamma regression tests: **24 / 24** passed.
- A few preexisting Python SQLite `ResourceWarning` diagnostics appear during tests; no failures.

## Required before genuine Phase 3C can be marked operational

1. A *separate service/account* independently collects Render deployment events (authenticated Render API response, service ID, deployed commit, status, time), and supervisor/PID/boot evidence (authenticated out-of-process supervisor). APEX-supplied env vars are insufficient.
2. A private Ed25519 signing key is provisioned and protected exclusively in the independent authority, ideally KMS/HSM; the APEX process cannot request arbitrary signing of its own claims.
3. The authority independently obtains transaction-consistent ledger copies or signed snapshot streams off the APEX host, validates source records against receipts, and signs monotonic checkpoints only after external capture is confirmed.
4. Each signed checkpoint is anchored in **durable remote append-only/WORM storage**, with server-assigned receipt timestamps, independent retention and no overwrite/delete permissions for APEX.
5. Multi-checkpoint continuity is verified across rollovers, including predecessor signatures, sequence monotonicity, revoked/rotated keys, service redeployments, partial writes, clock skew and checkpoint network outages.
6. An offline verifier uses a pinned **separately sourced** trust policy and key revocation list, distrusts unsigned/fallback boot evidence, verifies the independent collector's observation method and never promotes source data based solely on APEX declarations.
7. Apply full staging security/operational review before considering production capture. Historical 3,569 decisions never receive retroactive producer attestations.

## Fail-closed boundaries

- Untrusted/revoked key, boot/deploy conflict, broken signature, missing checkpoint, changed boot, tampered/truncated ledger, non-staging environment: `UNVERIFIED` or signing refusal.
- Declared `evidence_source` does **not** authenticate its source. Staging success explicitly carries a non-authentication caveat.
- No trade routing, learning promotion, schema migration, retroactive receipt creation, or production feature flag changes.

**Authority:** `BLOCKED_RESEARCH_ONLY`.
