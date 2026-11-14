# APEX 69.10.47 — Cumulative Candidate Release Governance & Promotion Reconciliation

**Status: RESEARCH CANDIDATE; NOT PROMOTED.**

## Scope and provenance

- Current archive: `apex-engine-main(20261114-103859).zip`.
- Independently available comparison baseline: `apex-engine-main(20261030-113020).zip`.
- User-provided November 14 audit instead compares to an October 31 tree. Counts are **not interchangeable**; the baseline used in this package is specified and SHA-256 hashed.
- Exact byte diff: **36 modified, 86 new, 0 removed** files (excluding transient caches).
- Canonical release remains `69.10.47`; database schema remains 8. No release manifest changes performed.
- Complete, SHA-256 backed inventory: `CHANGED_FILES_69_10_47_CANDIDATE.csv`; machine-readable reconciliation: `CANDIDATE_RECONCILIATION.json`.

## Workstream reconciliation

| Workstream | Modified | New | Removed | Proposed disposition |
|---|---:|---:|---:|---|
| `documentation_or_manifest` | 2 | 7 | 0 | Reconcile duplicate candidate manifests |
| `execution_safety` | 5 | 4 | 0 | Separate high-risk gate; keep dispatch blocked |
| `forecast_and_market_research` | 14 | 40 | 0 | Research/shadow only; keep evidence immutable |
| `other_or_runtime_review` | 4 | 4 | 0 | Manual owner review before promotion |
| `runtime_diagnostics` | 7 | 23 | 0 | Read-only candidates; verify health overhead |
| `tests_other` | 3 | 3 | 0 | Maintain regression coverage |
| `trigger_observatory` | 1 | 5 | 0 | Check query/read-only semantics and explicit repair |

## Execution and authority verification

- `engine/execution/traderspost_paper.py::dispatch` retains an **unconditional** `PAPER_EXECUTION_AUTHORITY_NOT_VERIFIED_69_10_40` raise before payload construction and network sending. It must **not** be removed in this governance change.
- SPXO/AM lifecycle classification and conservative blockers are present; lack of blockers is not authorization.
- Do not imply `is_tradeable`, successful scanner health, or paper account configuration grants order-routing authority.
- Any future activation requires a distinct review and integration tests of currently unreachable send code, daily limits, reconciliation, broker state and failure handling.

## Evidence and remaining gates

| Gate | Status | Evidence / next requirement |
|---|---|---|
| Inventory checksum and change mapping | PASS | Machine-readable exact archive SHA-256 + per-file hashes |
| Release/version integrity | PASS | 69.10.47 unchanged; schema 8 |
| Reported full suite | EXTERNAL EVIDENCE | Supplied audit reports 2,801 pass, 3 fail; not rerun here |
| Focused local regression tests | PASS | 25 SPXO/TradersPost/Stage 2/Trigger Observatory and 12 consolidation/gamma tests passed: 37 total |
| Flask app-level tests | BLOCKED | `test_operational_health.py` collection fails here due to missing `flask` |
| Three storage-capacity failures | NOT CLOSED | Repeat on host with ample `/tmp` free capacity and retain full logs |
| CI boot smoke + full suite | NOT CERTIFIED | Run required GitHub CI on candidate commit |
| Production SHA reconciliation | NOT VERIFIED | Get current deployed SHA and compare ancestor, change set, and files |
| Execution safety | PROVISIONALLY SAFE | Unconditional hard stop remains; confirm CI assertions |
| Promotion manifest/version bump | INTENTIONALLY DEFERRED | Create only after selecting a coherent release subset and approving it |
| Release to production | BLOCKED | No deployment performed |

## Pre-promotion release procedure

1. Commit this **additive governance documentation only** to a review branch. Do not overwrite runtime files from this package.
2. Verify baseline SHA and candidate SHA using the provided offline verifier, or record a new baseline and regenerate inventory explicitly.
3. Obtain deployed Render commit SHA, candidate Git SHA, and GitHub workflow run IDs; reconcile differences before promotion.
4. Isolate promotion streams: (A) observability and diagnostics, (B) SPXO/execution fail-closed safeguards, (C) forecast research, and (D) Trigger Observatory reporting changes.
5. Run the required smoke and pytest jobs on a provisioned environment. Do **not** blanket-ignore failing storage guard tests.
6. After choosing approved subsets, create an actual versioned `CHANGED_FILES` release manifest and bump `config/apex_release_manifest.json` only when authorized.
7. Verify scanner, canonical settlement, SPXO unknown/AM fail-closed handling, and disabled broker dispatch after deployment; preserve rollback SHA.

## Additional conflicts and cautions

- The current tree contains both top-level and `tools/engine/` premarket code. Do not assume either is the runtime authority without import-chain verification.
- `MANIFEST.json`, `MANIFEST.txt`, and `INTEGRATION_MANIFEST.txt` exist as candidate integration artifacts; none replaces the canonical versioned release manifest.
- Existing `ci/known_failures.txt` is effectively empty, so the `tests` GitHub CI job does not skip the three storage tests. An environment-induced failure can therefore block the required suite even if the informational job tolerates it.
- The uploaded audit is static/test-derived and did not verify Render state. This package has the same limitation.

## No operational changes

This build adds only governance files and an offline verifier. It does not change scanners, signals, canonical evidence, SQLite storage, release metadata, or any execution authority. Stage 3 stays deferred.
