# APEX 69.0 — Unified Historical Evidence Lifecycle Closure

## Objective
Close the live historical-evidence gaps identified in the August 23, 2026 production audit without changing trade decisions, confidence thresholds, risk rules, or execution authority.

## Production gaps closed

1. **Canonical decision evidence was not being captured.**
   - The Institutional Decision Object is now frozen into the existing durable `apex_evidence_pipeline.db` ledger after the authoritative IOS composition is complete.
   - Actionable decisions and abstentions are both captured. Only actionable rows are calibration-eligible; abstention counterfactuals remain isolated from calibration grading.

2. **The evidence ledger had no live SPX price samples.**
   - The scanner-owned process now feeds real SPX observations from the same source path used by HLCE into `price_samples`.
   - No synthetic or proxy price is fabricated.

3. **The canonical outcome grader was never scheduled.**
   - The scanner process now runs the existing outcome grader on a bounded cadence (`APEX_EVIDENCE_GRADER_SECONDS`, default 60 seconds).
   - Matured actionable decisions receive MFE/MAE/directional outcomes; attribution grading separately evaluates abstentions.

4. **Flow feature labels could be permanently missed.**
   - Session-close settlement now also scans prior feature-store sessions for unlabelled samples.
   - Recovery still requires actual persisted excursion evidence; missing outcomes are not fabricated.

5. **Market Memory remained cold.**
   - APEX 69 captures one observational Market Memory snapshot per ticker/session-state/day from the canonical decision lifecycle.
   - Capture is observational-only and independently disableable with `APEX_69_MARKET_MEMORY_CAPTURE_ENABLED=false`.

6. **Historical lifecycle health was fragmented.**
   - New endpoint: `GET /api/learning/evidence-lifecycle`
   - Scanner heartbeat now exposes `historical_evidence_lifecycle` and `feature_label_settlement` diagnostics.

## Guardrails

- No historical backfill is fabricated.
- No trade decision is changed.
- No execution authority is added.
- No confidence, threshold, or calibration policy is automatically changed.
- Automatic recalibration remains disabled.
- Human/governed promotion remains required.
- Existing abstention counterfactual isolation is preserved.

## Post-deploy verification

After the first live Institutional OS composition, `/api/learning/evidence-lifecycle` should show `decisions.captured > 0`.
After scanner ticks, `decisions.price_samples` should increase.
After the grading horizon matures (default 300 seconds), `decisions.graded` or `decisions.excluded` should increase and `pending` should not grow indefinitely.
After an after-hours/overnight settlement cycle, `feature_label_settlement.prior_session_recovery` in the scanner heartbeat will report whether the previously unlabelled flow samples were recovered or lacked excursion evidence.

## Validation

- New 69.0 lifecycle tests added.
- Existing evidence, decision attribution, dynamic-state calibration, canonical persistence, and feature-store tests exercised.
- Final focused validation: 46 passed.
- Expanded engine regression before final observability hook: 96 passed, 1 skipped because Flask is not installed in the validation container.
- `app.py`, `scanner_worker.py`, and all modified engine modules compile successfully.
