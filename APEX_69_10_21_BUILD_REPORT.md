# APEX 69.10.21 — Canonical Settlement Cohort Identity Reconciliation

## Purpose
Diagnose the proven divergence between canonical excursion persistence/readback and settlement retrieval without changing matching, evidence, leakage, learning, or execution semantics.

## Production basis
69.10.20 production telemetry verified 1,707/1,707 exact post-commit excursion readbacks with zero missing readbacks and zero identity mismatches, while settlement continued to report zero canonical excursion rows for its requested feature cohort.

## Implementation
- Adds `reconcile_settlement_excursion_cohort()` to compare settlement-requested canonical sample IDs with all persisted canonical excursion IDs for the same session.
- Exposes exact counts for requested-with-excursion, requested-without-excursion, excursion-not-requested, identity-map-only requested, and feature-only requested IDs.
- Emits bounded diagnostic samples with exact persisted session/decision-time/legacy-key provenance from each divergent side.
- Adds per-session reconciliation to settlement reports and an aggregate reconciliation summary to `settle_pending_labels()`.
- Advances release/runtime reconciliation truth to 69.10.21.

## Guardrails
- Exact `CANONICAL_FEATURE_SAMPLE_ID` equality only.
- Session-scoped comparison only.
- No identity reconstruction.
- No fuzzy/nearest timestamp matching.
- No synthetic P/L, MFE, MAE, excursion, or label evidence.
- No historical backfill.
- No settlement recovery behavior added.
- No decision-authority or execution-authority change.
- Existing 69.10.20 post-commit readback remains intact.

## Validation
- APEX 69.10.x lineage: 133 passed.
- Focused feature-store / flow-P&L / settlement / historical-similarity regression: 212 passed.
- New 69.10.21 closure tests: included in lineage suite.
- Python compileall: passed.
