# APEX Forward Provenance — Phase 3B (isolated crash/restart staging)

**Status:** research-only implementation and disposable synthetic tests. No independent deployment attestation and **no** migration, history rewrite, trading authority, receipt reconstruction, or producer promotion.

## Purpose

Phase 3B tests the failure boundary between **committed source data** and a **separately committed forward provenance ledger**. The current integration intentionally cannot guarantee atomicity across those databases. This harness checks that partial failures remain explicitly incomplete instead of attempting to fabricate missing provenance.

## Files

- `scripts/apex_forward_phase3b_staging.py` — new Phase 3B CLI and fresh-interpreter fault-injection workers (temporary, synthetic SQLite files only).
- `tests/test_forward_provenance_phase3b.py` — two new tests for the rehearsal and CLI contract.
- Other Phase 1, Phase 2, and Phase 3A files are included for cumulative installation. Existing production code paths are not modified by this phase.

## Run from a source checkout with the cumulative Phase 3A patch integrated

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase3b_staging --json
PYTHONPATH=. python -m unittest \
  tests.test_forward_provenance \
  tests.test_forward_provenance_verifier \
  tests.test_forward_provenance_phase3a \
  tests.test_forward_provenance_phase3b -v
PYTHONPATH=. python -m unittest discover -s tests \
  -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -v
```

Do **not** set `APEX_FORWARD_PROVENANCE_ENABLED=1` on production. The standalone rehearsal enables provenance **only inside child processes**, pointing `fp.DEFAULT_DB` at a newly created temporary directory. It does not read `/data` or production SQLite. Its subprocess `--worker` option rejects paths without the synthetic temporary-directory marker.

## Cases exercised (11)

1. Fresh child process writes calculate → gamma persist → decision persist and the hash chain validates.
2. Retried existing synthetic source records are `INSERT OR IGNORE` duplicates and do not append new receipts.
3. Hard termination **after source gamma commit but before receipt** leaves a detectable missing gamma receipt.
4. Retry of that committed gamma does not invent a historical receipt.
5. Hard termination **after gamma receipt but before decision** leaves an orphan gamma receipt.
6. Hard termination **after source decision commit but before receipt** leaves a detectable missing decision receipt.
7. Retry of that decision does not backfill missing receipt.
8. A fresh child process attempts to link a decision to another process's gamma receipt and records `UNVERIFIED` with no execution ID.
9. Hard termination inside an open SQLite ledger transaction leaves no half-committed event and preserves the previous valid chain.
10. Unwritable synthetic receipt location leaves the committed synthetic source row intact but no ledger and no authenticating receipt.
11. A forked child inherits no attested boot identity (`boot_id=None`), so it cannot use the parent's boot claim.

Each injected hard crash intentionally uses process exit code 73. Test harness asserts that code and inspects the resulting temporary artifacts. All subprocesses are bounded by 15-second timeouts.

## Acceptance boundaries

- **PASS** only establishes the failure-mode and existing fail-closed contracts against simulated sources and the real receipt-writing functions.
- The `audit()` function provides a **read-only synthetic discrepancy report**, not a repair/migration operation.
- No cross-database atomic commit is implemented; missing receipts after a real partial commit stay unauthenticated. Production recovery needs an explicit business-safe retry policy and external verification, not fabricated historical events.
- `verify_chain()` checks local hash-chain consistency, **not** independence or completeness; an entirely missing tail needs independently signed checkpoints (Phase 3C).
- The current Phase 1 collector can append an unlinked decision receipt with `linkage_class="UNVERIFIED"` after a process restart, rather than claiming a new gamma execution.
- Running an isolated staging harness inside a Render shell does **not** mean production capture is enabled or that real attestations exist.

## Tested locally

- Phase 3B CLI: **11/11 synthetic cases PASS**.
- Phase 1–3B forward provenance unit tests: **16/16 PASS** (Python 3.13; existing tests emit optional SQLite ResourceWarning notices).
- Existing Stage 3B.3.15 regression test suite: **24/24 PASS** against a locally extracted November 21 full source checkout.

**TOTAL: 40 automated tests PASS, plus 11 synthetic CLI checks.** These are local results, not a production rollout.

## Pending Phase 3C

- Independent, authenticated deployment/boot attestations (not in-process signatures).
- Externally retained, signed, timestamped checkpoints anchoring complete ledger heads.
- Read-only reconciliation of actual source and receipt store copies at a consistent snapshot boundary.
- Explicit disposition for orphan receipts, missing receipt after source commit, writer outages, and source/receipt event ordering.
- Safe isolated staging rollout and operational readiness review before any production activation.

**Authority remains:** `BLOCKED_RESEARCH_ONLY`; historical 3,569 decision rows unchanged.
