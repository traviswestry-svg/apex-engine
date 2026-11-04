# APEX — Expected-Move Source Eligibility & Shadow Forecast Quality Segmentation

**Candidate only — read-only / SHADOW_RESEARCH_ONLY. Not production-certified.**

## Source reconciliation

Started with the November 2, 2026 repository as reconciled in the prior **Forecast Range Failure Decomposition & Quote Integrity Research Visibility** candidate, which already carries the prior canonical selection, premarket evidence, outcome attribution, expected-move quote provenance, and range-failure diagnostics. The patch must be applied to that reconciled branch rather than directly to an unreconciled November 2 base. Canonical release metadata remains **69.10.47**.

## Files changed

- `engine/premarket_directional_features.py`
- `tests/test_expected_move_source_quality_segmentation_candidate.py` (new)
- This report

## Implemented

1. `expected_move_source_eligibility(morning)` classifies **VERIFIED**, **DEGRADED**, **REJECTED**, **LEGACY_UNVERIFIED** and **INCONSISTENT_AUDIT**, based exclusively on frozen Morning Brief evidence. VERIFIED requires the prior frozen `SOURCE_VERIFIED` label, a provider-source verified flag, no frozen issues, structurally complete two-sided call/put quote records with acceptable archived quote ages, and arithmetically verified forecast-center construction. Nothing is refetched, timestamps are not substituted, and a contradictory archive is not promoted.
2. `source_quality_coverage(mornings)` counts source-quality coverage among same-day canonical premarket origins only and explicitly excludes missing/invalid canonical origins. Its denominator is not revisions or completed outcomes.
3. The existing `archive_diagnostics` detail rows expose `expected_move_source_eligibility` without rereading providers; `archived_diagnostics` also returns `source_quality_coverage`.
4. The existing `shadow_outcome_attribution` retains **all exactly matched, internally verified** retrospective outcome rows for historical descriptive use; each row receives source eligibility. It additionally returns `source_quality_segmentation` with count, containment count, descriptive fraction, mean absolute forecast-center residual, and explicit source-quality cohorts. The original `eligible_sessions` count continues to mean all exact outcome matches, while `comparison_ready` is now **strict-source-verified-only**, with an explicit separate `all_source_descriptive_sample_ready` flag. This is a deliberate semantic tightening; consumers should verify the meaning of these flags before relying on them.
5. Read-only IV-alternative assessment reports **NUMERIC_IV_AND_IMPLIED_MOVE_ARCHIVED_SOURCE_NOT_INDEPENDENTLY_VERIFIED** only if both numeric frozen ATM IV and IV-derived expected-move values are present. It does not trigger IV fallback or certify an IV quote's event-time provenance.

## November 4 expected result

The frozen last-trade SPXW call and put with zero bid/ask and >45,000-second quote age remain `DEGRADED_SOURCE_EVIDENCE`, classified `DEGRADED`, not strict-research-eligible. The October 30 earlier forecast without an archived source audit is `LEGACY_UNVERIFIED`. Those two completed outcomes remain visible in distinct **descriptive** cohorts and do **not** count toward the `VERIFIED` strict comparison sample. No new source-verification or model performance claim is warranted.

## Governance and tests

- **92 selected tests passed**: new source eligibility, outcome matching, source integrity, premarket and canonical research, consolidation, gamma-coverage, gamma-transition integrity and gamma-stability suites.
- Python module compilation passed.
- Full repository `pytest -q --maxfail=1` blocked in collection: `ModuleNotFoundError: No module named 'flask'` from `engine/institutional_decision_integrity.py`.
- Two other existing ES RTH session-boundary tests (`test_prior_rth_metadata_and_incomplete_reason` and `test_mixed_dates_select_latest_complete_session`) failed in the expanded selection **and were independently reproduced against the unchanged previous candidate**; they were not modified by this build. They must be reconciled in normal CI before any release.
- No new dependencies, environment variables, configuration registry entries, database tables or migrations; no changes to production forecast generation, straddle/IV selection, option-provider adapters, canonical persistence, Evening Recap official scoring, or execution authority.

## Release gates

1. Merge this changed-files-only candidate into the exact branch containing all prior reconciled candidates. Confirm diff and run complete CI with the application's real dependencies.
2. Investigate and resolve baseline ES session-boundary test failures; run release-truth, configuration registry, gamma-transition and canonical-lifecycle checks in a full app environment.
3. Check the production research endpoint for `source_quality_coverage`, `details[].expected_move_source_eligibility`, `shadow_outcome_attribution.source_quality_segmentation`, and the exact outcome rows' source tags.
4. Confirm November 4 is `DEGRADED` due to stale last-trade fallback; October 30 is `LEGACY_UNVERIFIED`; preserve both official canonical records and official recap grading.
5. Keep current forecast authority and paper/live execution gates unchanged. A classification does not authorize modifying or rejecting the official expected-move source.
