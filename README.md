# APEX Canonical Settlement Eligibility & Pending Evidence Classification — Completion Candidate

Source baseline: `apex-engine-main(20261016-123417).zip` (69.10.37). Changed-files-only package.

## Overlap audit
The source ALREADY includes `engine/canonical_settlement_eligibility_38.py`, its `settle_pending_labels()` integration in `engine/feature_store_writer.py`, and focused tests. This candidate **does not overwrite the existing integration** or create another settlement writer.

## Additions
- Read-only, mutually exclusive pending evidence partition: `EXCURSION_PRESENT_UNLABELLED`, `NO_EXCURSION_LIFECYCLE_PRESENT`, and `NO_EXCURSION_NO_LIFECYCLE`.
- Explicit partition integrity checks for labelled/unlabelled, pending, and excursion populations; returns `INTEGRITY_MISMATCH` rather than silently reporting READY if partitions disagree.
- Regression tests verifying partition coverage, no synthetic label writes, and no database creation when an audit path is absent.
- Existing exact canonical sample-ID joins, bounded examples, observational-only semantics, and all existing label-write logic remain unchanged.

## Verification performed
`python -m pytest -q tests/test_apex_69_10_38_settlement_eligibility.py tests/test_apex_69_10_35_canonical_settlement_cohort_identity_alignment.py tests/test_apex_69_10_21_canonical_settlement_cohort_identity_reconciliation.py` -> 10 passed.
`python -m compileall -q engine/canonical_settlement_eligibility_38.py` -> passed.
Local full pytest collection -> blocked by missing runtime dependency `flask` (68 collection errors). **Not a CI pass.** Run GitHub Actions full CI with requirements installed before promoting.

## Deployment and release
This is a candidate patch only, no DB migrations, no env vars, no new routes, no trading authority, no release bump. Current manifest remains 69.10.37. Competing 69.10.38 scope must be reconciled before assigning a production version. Verify production counts, output performance, and source DB accessibility on Render. Existing `settle_pending_labels()` invokes the audit once per call.

## Apply
Copy these two paths into the same relative locations in the current repository, review the diff, run CI, and deploy only after approval.
