# APEX Phase 4E — External Infrastructure Integration & Production Authorization Readiness

**Build type: read-only, staging research. Verdict: `NO_GO`.**

Phase 4E is an **integration readiness auditor**, not a provisioning agent, certificate authority, independently supervised scanner, or permission to activate forward provenance. The external collector, separately managed signing keys, off-host immutable retention and independent scanner process-origin evidence are **not deployed** by this patch.

## New components

- `engine/forward_provenance_phase4e.py`: fail-closed evidence-manifest and offline artifact hash checker. Maintains seven readiness gates, five hard blockers, `NO_GO`, and historical exclusion. No network, database writes, mutable evidence, trading, or authorization endpoints.
- `scripts/apex_forward_phase4e_readiness.py`: offline read-only JSON report. Exits `2` by design, even with complete operator-provided local artifacts.
- `scripts/apex_forward_phase4e_staging.py`: disposable 12-check rehearsal, no production files or API credentials.
- `tests/test_forward_provenance_phase4e.py`: 14 security and read-only unit tests.

The package is **cumulative**: overlay its `apex-engine-main/` directory on your complete current APEX repository; the patch by itself is not a standalone copy of the full repo. Review diffs before merging, particularly if the current repository has newer code than the source baseline.

## Readiness gates

1. `code_integrity`: deployment SHA, independently witnessed source SHA, test evidence.
2. `collector_independence`: direct provider observations, collector identity, isolation from APEX.
3. `protected_signing`: external key custody, signing policy, revocation.
4. `external_checkpoint`: externally anchored checkpoints, actual immutable retention, continuity.
5. `process_origin`: independently supervised scanner boot and process-to-gamma/decision linkage.
6. `resilience`: restart/outage validation and external monitoring.
7. `safety_isolation`: execution-boundary proof, unmodified historical population, rollback.

A SHA-256 comparison of an operator-supplied local file to an operator-supplied hash is **not** independent authentication. The auditor treats each such match as *local file consistency only*. It does not trust `"VERIFIED"`, `"GO"`, or references provided by a user. Every gate remains insufficient or `NO_GO` even if all local artifact hashes match. No `--approve`, `--enable`, `--sign`, `--promote`, or `--production` action exists.

## Render Shell commands — synthetic and non-invasive

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase4e_staging --json
PYTHONPATH=. python -m unittest tests.test_forward_provenance_phase4e -v
PYTHONPATH=. python -m unittest \
  tests.test_forward_provenance tests.test_forward_provenance_verifier \
  tests.test_forward_provenance_phase3a tests.test_forward_provenance_phase3b \
  tests.test_forward_provenance_phase3c tests.test_forward_provenance_phase3d \
  tests.test_forward_provenance_phase3e tests.test_forward_provenance_phase4a \
  tests.test_forward_provenance_phase4b tests.test_forward_provenance_phase4c \
  tests.test_forward_provenance_phase4d tests.test_forward_provenance_phase4e -q
PYTHONPATH=. python -m unittest discover -s tests \
  -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -q
```

To obtain an initial `NO_GO` report:

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase4e_readiness
# Expected exit status 2 (unmet readiness), not a test failure.
```

## Optional offline evidence inventory

Use a dedicated **disposable audit-copy directory**, not `/data` or `/audit-copy`. Create a manifest with exactly these top-level keys: `schema_version`, `mode`, `gates`. Set `schema_version` to `4E.1` and `mode` to `READ_ONLY`. Each `gates` entry is a mapping of gate-specific artifact names to `{"path":"basename.json","sha256":"<64 lowercase hex>"}`. The script reads only existing regular non-symlink files named by **basename** inside the evidence directory (maximum file size 32 MiB), verifies hashes, and reports missing or invalid references. It never verifies the truth, provenance, custody, or independence of those documents.

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase4e_readiness \
  --manifest /path/to/manifest.json \
  --evidence-dir /path/to/disposable-copies \
  --phase4d-report /path/to/phase4d-report.json
```

The optional 4D report must be a **staging** report; forged `VERIFIED`/`GO` claims are rejected. No source-row or evidence-database writes occur.

## What must really be deployed before reconsidering production activation

**Collector:** a separately administered, restricted-permission worker that fetches authenticated Render deployment facts directly from the Render API with a dedicated scoped token, securely authenticates to a downstream authority, and retains unaltered timestamped collection evidence independent of APEX. Running the collector in the APEX shell is not independent observation.

**Signer:** an independently administered signing service with non-exportable KMS/HSM signing keys, authenticated collector identity, externally enforced authorization policy, key rotation, revocation and durable replay protection. APEX cannot create or set those claims by itself.

**Checkpoint authority:** an independently administered, immutable object store with retention lock, write-once policy, durable public-key pins, separately managed identity, externally anchored ledger heads, continuity / recovery checks and tested access revocation. Local SQLite and its triggers are not WORM.

**Process-origin supervisor:** independently supervised startup attestations binding a unique boot/process identity and executable image to actual gamma computation, canonical snapshot commit and decision receipt, with replay resistance. A provider deployment record does not establish scanner process identity.

**Production approval:** separate human security review, positive operational monitoring and a new explicitly reviewed activation mechanism, isolated from signal scoring and all broker/order paths. This patch intentionally cannot produce GO; making GO possible will require a separate audited design and code release.

The existing **3,569 historically linked decisions** are excluded from retroactive authenticated reclassification. Existing production provenance collection must remain disabled. Migration authority: `BLOCKED_RESEARCH_ONLY`.

## Local validation for this release

- 12/12 isolated Phase 4E staging checks.
- 14/14 new Phase 4E tests.
- 105/105 combined forward provenance tests against the Nov 21 APEX baseline + patch overlay.
- 24/24 existing gamma regression tests.
- **129/129** combined targeted automated tests. Existing unrelated SQLite resource warnings may appear in older tests.

This is **local validation only**. Do not represent it as successful deployment of an independently operated external trust infrastructure.
