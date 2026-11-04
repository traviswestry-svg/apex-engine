# APEX — Decision-Time Option Quote Provenance & Expected-Move Source Integrity

**Status:** candidate; requires full CI and staging verification before deployment.
**Baseline:** apex-engine-main(20261102-231112).zip, with prior research-candidate integration context. Canonical release version remains **69.10.47**. No release promotion.

## Scope

- The already-normalized Polygon SPX option snapshot now retains the **provider quote event timestamp** (distinct from fetch/capture timestamp) on each contract. The normalization accepts numeric epoch seconds/milliseconds/microseconds/nanoseconds or timezone-aware ISO time; missing or ambiguous time stays absent.
- The ATM pair selection diagnostics now preserve each leg's contract ID, provider, expiration, bid, ask, mid, last, selection method, IV, provider quote timestamp and quote age.
- New pure `engine.expected_move_source_integrity.audit()` validates decision-time quote ages (advisory threshold: 120 s), spread (advisory threshold: 25%), two-sided mids, last-trade fallback, selected source/expiration identity, and consistency of source premium or IV with the frozen one-sigma move. Suspicious source evidence is marked `DEGRADED_SOURCE_EVIDENCE` or `REJECTED_INTEGRITY`, never re-labeled as verified.
- `engine.morning_brief.generate_morning_brief()` freezes the additive `forecast_provenance_diagnostics.expected_move.decision_time_source_integrity` into the Morning Brief **before** persistence. Legacy expected-move fields are populated from same-decision evidence, with missing fields explicitly listed. The earliest leg event time is the legacy top-level timestamp; each leg retains its own timestamp.
- The existing expected-move model remains straddle-first / IV fallback. This build does **not** block, change or promote forecasts based on the new advisory classification, nor modify historical records or evening scoring. No background fetching or independent provider calls.

## Validation performed

- 11/11 new focused source-integrity unit tests passed (synthetic observations; including Polygon nanoseconds, missing/future/stale quote timestamps, expiration/provider mismatch, straddle/IV arithmetic, quote fallback, legacy adapters).
- 98/98 selected premarket, Morning Brief, canonical selection, forecast-center, gamma, consolidation tests passed.
- Additional focused release/governance/gamma run: **44 passed, 1 failed** due solely to `ModuleNotFoundError: No module named 'flask'` while importing app.py in test_configuration_governance.
- Full repository `pytest -q --maxfail=1`: **collection stopped** at `ModuleNotFoundError: No module named 'flask'` in institutional_decision_integrity; not an assertion failure of this patch.
- Python compile verification passed. No new environment variables, no DB schema changes, release metadata remains 69.10.47.

## Constraints / caution

- Quote timestamps may be absent from the provider. Do not infer them from arrival time; the audit degrades rather than fabricates.
- The captured expiration represents the expiration selected by the current upstream code (currently assumes 16:00 ET for expiry-time calculation). This build does not independently certify AM-versus-PM settlement conventions or that the selected strike is economically optimal.
- In last-trade fallback, provider quote time is not necessarily the last **trade** event time; fallback always degrades.
- Advisory age/spread limits are first-pass conservative research thresholds, not live trade eligibility standards.
- Existing historical canonical records remain untouched and retain missing source provenance.
- Full dependency-installed CI, gamma-transition suite, app route validation, and premarket staging checks are mandatory before deployment. No change in execution authority.

## After CI / deployment

1. Generate a **new** same-day PREMARKET Morning Brief, not a retroactive historical reconstruction.
2. Inspect `structured.forecast_provenance_diagnostics.expected_move.decision_time_source_integrity` and its `quote_legs.call` / `quote_legs.put` event times and quality.
3. Verify the frozen provenance persists across Evening Recap, revisions and restarts without mutation.
4. Expect `DEGRADED_SOURCE_EVIDENCE` if provider lacks event timestamps or quotes are older than the advisory threshold. Do not treat it as proof that the reference spot, selected expiration or premium was sound.
