# APEX Phase 4B — Restricted Protected Attestation Signer (Research)

**State: STAGING_ONLY / NO_GO.** Validated only with simulated collector data and short-lived test keys. Phase 4B **does not deploy an independent service**, connect to a real KMS/HSM, authenticate the live Render API response independently, observe scanner PID or boot, or create a durable anti-replay register. It never promotes any of the 3,569 historical decisions and does not alter trading behavior.

## Source additions

- `engine/forward_provenance_signer.py` — two domain-separated Ed25519 signatures (collector envelope + signer attestation); pinned public-key policy; identity and freshness checks; explicit refusal for fixture observations, unverified process claims, invalid/different signing key, revoked keys, expired keys, and replay collisions.
- `tests/test_forward_provenance_phase4b.py` — 16 synthetic edge-case and tamper tests.
- `scripts/apex_forward_phase4b_staging.py` — disposable in-memory test rehearsal; no environment credentials or production files.

## Supported assurance

The signer issues only `DEPLOYMENT_OBSERVATION_ONLY` under `ISOLATED_STAGING` with `NO_GO`. The observer envelope must have a valid signature from a collector key independently *pinned in the signing policy*. The signer has no way to prove that the collector honestly obtained its information from Render: it checks the signature and the normalized Phase 4A report's consistency. Independent network source collection, operator-owned trust policy and key custody, and tamper-resistant anti-replay storage must still be installed before considering real-world attestation.

**Do not install a signing private key, Render token, or trust anchor in the APEX web/cron application environment.** In this research code, the injected signer object is deliberately a staging-only interface, **not protected production key custody**. `reserve_nonce` is an injected atomic callback; the rehearsal's in-memory set does not survive process restarts and does not satisfy production replay prevention. For future Phase 4C, use atomic off-host persistent reservation and durable immutable checkpoint sequence.

## Run safely in an isolated source checkout

```
PYTHONPATH=. python -m scripts.apex_forward_phase4b_staging --json
PYTHONPATH=. python -m unittest tests.test_forward_provenance_phase4b -v
PYTHONPATH=. python -m unittest \
  tests.test_forward_provenance tests.test_forward_provenance_verifier \
  tests.test_forward_provenance_phase3a tests.test_forward_provenance_phase3b \
  tests.test_forward_provenance_phase3c tests.test_forward_provenance_phase3d \
  tests.test_forward_provenance_phase3e tests.test_forward_provenance_phase4a \
  tests.test_forward_provenance_phase4b -q
PYTHONPATH=. python -m unittest discover -s tests \
  -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -q
```

Expected Phase 4B JSON: `checks_passed=16`, `checks_total=16`, `environment=DISPOSABLE_SYNTHETIC_ONLY`, `verdict=NO_GO`, `production_activation_authorized=false`.

The patch is cumulative with Phase 4A and is overlaid on the complete November 21 APEX source tree; it is not a standalone replacement application. Existing test warnings regarding unclosed SQLite connections remain from pre-existing test code.

## Phase 4C blockers

1. Independently operated collector using authenticated Render API observations and independently established collector identity.
2. External signing authority with protected private-key custody (KMS/HSM) and least-privilege request authentication.
3. Durable off-host, atomic anti-replay reservation and append-only checkpoint archive, including continuity across restarts.
4. Documented key rotation, revocation source, audit trails, and operational testing across outages.
5. Independent scanner process-origin supervisor evidence (Render deployments do not expose process/boot data).

Production activation and historical promotion remain `NO_GO` / `BLOCKED_RESEARCH_ONLY`.
