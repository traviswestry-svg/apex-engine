# APEX Phase 3D — Read-Only Operational Verification

**Deliverable:** staging-only operational verifier, cumulative with Phases 1, 2, 3A, 3B, and 3C. Source baseline: Phase 3C research patch; production not modified.

## Added files

- `engine/forward_provenance_operational.py`: read-only reporting against an existing *audit copy*, with SHA-256 ledger-chain check, boot/process **claim** counts, per-kind event counts, incomplete gamma→decision receipt chains, receipt inventory coverage when caller supplies an optional inventory, optional Phase 3C signed staging checkpoint verification, and freshness/revocation classifications.
- `scripts/apex_forward_phase3d_report.py`: standalone JSON-report CLI. Exit code `0` only for **STAGING_CORROBORATED_OPERATOR_FACTS**; exit `2` for all unverified/failure states.
- `scripts/apex_forward_phase3d_staging.py`: disposable synthetic rehearsal running Phase 3D unit tests; no production data access.
- `tests/test_forward_provenance_phase3d.py`: nine isolated tests for corroboration, missing receipts, stale checkpoint, revoked key, corrupted ledger, forged statements, mismatched checkpoint head, optional inventory coverage and unchanged database bytes.

## Security and interpretation

- This patch **never emits a real-world `VERIFIED` state** because Phase 3C's signing service still only signs operator-supplied facts in synthetic staging. Staging success is `STAGING_CORROBORATED_OPERATOR_FACTS`, with `authentication=NOT_REAL_WORLD_AUTHENTICATION` and `promotion_authority=NONE`.
- A pinned signing key and separate trust policy are required for staging corroboration. Revocation overrides allowlisting. All signed statements must be cryptographically verified. Signed checkpoint head + sequence must match the audited ledger, and signed checkpoint must fall inside the freshness window.
- `STALE_CHECKPOINT` means *cryptographically valid, allowed-key, matching-head staging checkpoint* older than the configured threshold; it is **not** a statement about independent off-host source collection.
- `MISSING_RECEIPT` applies to an explicitly requested decision ID absent from the ledger (or duplicated). If no independent decision inventory was provided, the report **cannot infer** missing records from a count of ledger rows alone.
- `CHAIN_INTEGRITY_FAILURE` means the existing chain verifier rejected the audit copy. Local hash-chain integrity is insufficient proof of historical authenticity or completeness.
- Runtime boot IDs, process IDs and commit SHAs collected from ledger are only **untrusted claims**. Counts cannot authenticate scanner boots.
- No network, no live Render API calls, no new signing keys for the operational reporter, no SQLite writes. Audit copies must be supplied externally and should remain outside `/data`. The test harness uses temporary synthetic files and ephemeral test-only signing keys.
- The CLI can load **operator-supplied** source decision IDs from JSON to calculate missing receipt *coverage*; those IDs have no independent source-row authentication unless the operator establishes it separately.

## Safe tests after adding patch to an isolated checkout

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase3d_staging --json
PYTHONPATH=. python -m unittest \
  tests.test_forward_provenance tests.test_forward_provenance_verifier \
  tests.test_forward_provenance_phase3a tests.test_forward_provenance_phase3b \
  tests.test_forward_provenance_phase3c tests.test_forward_provenance_phase3d -v
PYTHONPATH=. python -m unittest discover -s tests \
  -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -v
```

## Read-only operational report on a staging audit copy

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase3d_report \
  --ledger /path/to/existing/offhost-audit-copy.db \
  --decision-id SYNTHETIC_DECISION_ID
```

Expect `UNVERIFIED` with metrics in the absence of external bundle inputs. To check a staging-only signed bundle using externally managed inputs:

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase3d_report \
  --ledger /path/to/existing/offhost-audit-copy.db \
  --decision-id SYNTHETIC_DECISION_ID \
  --bundle /path/to/existing/staging-bundle.json \
  --pinned-public-key /path/to/existing/staging-pinned-public-key.bin \
  --trust-policy /path/to/existing/staging-trust-policy.json \
  --max-checkpoint-age-seconds 900
```

All paths above are illustrative. **Do not create fake attestations or configure production capture merely to make the verifier return `ok: true`.** When no existing audit copy is available, use only the disposable rehearsal.

## Local validation results

- Phase 3D staging rehearsal: **9/9 checks passed**.
- Combined Phase 1–3D provenance tests: **27/27 passed**.
- Existing Stage 3B.3.15 gamma receipt regression tests: **24/24 passed**.
- Python 3.13 emitted ResourceWarnings for SQLite connections in pre-existing supporting code; no test failures.
- No real independent Render deployment attestation, off-host WORM store or process-supervisor authentication has been integrated. **This does not complete the operational Phase 3C trust boundary.**

## Next milestone

Phase 3E production activation readiness should *not* authorize production until an actual independently managed collector, protected signing authority, durable off-host append-only checkpoint storage, and complete multi-checkpoint continuity/revocation tests have been demonstrated in staging. Existing 3,569 historical decisions must remain untouched and unauthenticated at the producer-process level.

**Authority:** `BLOCKED_RESEARCH_ONLY`.
