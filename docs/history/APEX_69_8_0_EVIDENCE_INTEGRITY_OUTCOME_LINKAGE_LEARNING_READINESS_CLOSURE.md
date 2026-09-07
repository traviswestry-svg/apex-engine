# APEX 69.8.0 — Evidence Integrity, Outcome Linkage & Learning Readiness Closure

## Objective

APEX 69.8.0 closes the highest-value post-69.7.1 decision-integrity gap without adding a new engine or promoting observational intelligence. The release makes pre-consensus evidence eligibility fail closed, links Trigger Observatory records to canonical grading outcomes, and exposes observational trigger-effectiveness measurements while preserving all existing execution and promotion boundaries.

## 1. Pre-consensus evidence eligibility fails closed

`engine.decision_reasoning_contracts.build_engine_opinions()` no longer grants `FULL` eligibility when `evaluate_evidence_eligibility()` raises.

The 69.8.0 fallback is:

- state: `INELIGIBLE`
- weight factor: `0.0`
- consensus eligible: `false`
- execution authority: `false`
- reason: `ELIGIBILITY_EVALUATION_FAILED`

The degradation is also sent to the existing silent-degradation observability layer. Failure of observability itself cannot weaken the fail-closed result.

This is the only intentional production decision-quality behavior change in 69.8.0.

## 2. Trigger Observatory → canonical outcome linkage

The existing Trigger Observatory store is upgraded additively to schema v2. Existing 69.7.1 databases are migrated in place by adding nullable linkage fields; existing trigger chronology is preserved.

Canonical triggers now persist their `decision_id`. `engine.outcome_grader` performs a best-effort observational synchronization after grading so Trigger Observatory records can retain:

- canonical grade status
- canonical grade label
- canonical grade payload
- canonical graded timestamp

The grade remains owned by the canonical evidence/outcome pipeline. Trigger Observatory never creates, edits, or promotes a grade.

## 3. Trigger effectiveness

A new read-only endpoint is registered:

- `GET /api/triggers/effectiveness`

It reports grouped observational statistics including:

- sample size
- five-minute excursion count
- five-minute favorable rate
- canonical graded links
- canonical wins/losses
- canonical win rate where available
- average MFE and MAE magnitude

Five-minute excursion outcomes remain explicitly separate from canonical trade grades. No trigger statistic changes consensus, confidence, eligibility, risk, sizing, execution, or policy automatically.

## 4. Learning readiness

69.8.0 deliberately reuses the existing canonical historical-readiness/evidence-readiness surfaces rather than adding a duplicate readiness engine. Production operators should use the existing readiness endpoints to verify graded-outcome accumulation and the `MIN_GRADED` gate before any learned behavior is promoted.

No calibration threshold, confidence formula, gamma threshold, HLCE weight, Tick Momentum authority, or Microstructure authority is changed in this release.

## 5. Governance cleanup

- `engine.canonical_decision` is relabeled in the Capability Registry as compatibility-only and has no decision authority; the live canonical authority remains `engine.institutional_decision_object`.
- `engine.outcome_grader` is removed from the consolidation test-only allowlist because it is runtime-reachable through the historical evidence lifecycle.

## Authority boundaries

- New execution authority: **none**
- New broker mutation: **none**
- Automatic policy promotion: **none**
- Trigger-effectiveness production effect: **observational only**
- Tick Momentum promotion: **none**
- Microstructure promotion: **none**

## Validation

Dedicated 69.8.0 regression coverage verifies that an eligibility-evaluator exception produces zero consensus-eligible evidence and that canonical trigger records can be linked to genuine persisted grading results without gaining behavioral authority.
