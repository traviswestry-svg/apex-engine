# APEX 69.6.0 — Gamma Capacity, Structure Durability & Pre-Consensus Evidence Eligibility

## Scope

This release implements three decision-quality recommendations without adding a new directional engine:

1. **Gamma Stabilization Capacity** — normalizes the immediate expiration's absolute net-gamma ratio by the live expected-move fraction of spot. Capacity is `UNAVAILABLE` when a real expected-move input is absent; no denominator is fabricated.
2. **Gamma Structure Durability** — computes 0DTE, 0–1DTE, and <=7DTE shares from absolute exposure by expiration and classifies durability as HIGH/MEDIUM/LOW.
3. **Evidence Eligibility** — inserts an explicit pre-consensus gate with `FULL`, `DISCOUNTED`, `CONTEXT_ONLY`, `WATCH_ONLY`, and `INELIGIBLE` states. Machine-readable reasons are retained for dashboard and evidence-graph inspection.

## Key safeguards

- Flow Excitation is not double-discounted. The existing `independence_factor` remains the sole numerical burst-redundancy discount; eligibility records the reason/state only.
- Stale or context-only evidence remains visible but cannot vote in consensus.
- Event-imminent/release evidence becomes WATCH_ONLY for new consensus formation.
- Low gamma durability makes dealer gamma context-only; weak capacity applies a bounded dealer-evidence discount.
- No execution authority is introduced.
- Gamma capacity does not become available without a real expected-move value.

## Dashboard

The Dynamic State panel now displays gamma capacity, gamma structure durability, 0–1DTE concentration, and the evidence-eligibility funnel with effective independent evidence.

## Validation

Focused regression suite covers gamma maturity concentration, no-fabrication capacity behavior, single-discount flow semantics, context/watch eligibility exclusion, eligibility summaries, existing dynamic-state behavior, calibration governance, and decision-reasoning consolidation.
