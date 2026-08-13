# APEX 25.0 — Institutional Decision Integrity Engine

Release identity: `25.0.0_INSTITUTIONAL_DECISION_INTEGRITY`

## Purpose

APEX 25.0 is a decision-governance layer, not another signal generator. It audits the evidence already produced by APEX and prevents missing, stale, failed, disabled, or unconfigured evidence from being interpreted as neutral confirmation.

## Delivered

- Canonical evidence-health model covering market state, institutional intelligence, flow, dealer positioning, multi-timeframe intelligence, market memory, historical similarity, and confidence calibration.
- Explicit evidence states: `FRESH`, `STALE`, `MISSING`, `FAILED`, and `NOT_CONFIGURED`.
- Critical-source protection: missing or stale live market state forces `STAND_DOWN`; degraded institutional intelligence caps advisory confidence at 40%.
- Integrity-adjusted confidence with a transparent confidence ceiling and reasons for every reduction.
- Explainable institutional decision record containing the primary thesis, counter-thesis, supporting evidence, opposing evidence, degraded evidence, invalidation, and minimum-evidence result.
- Execution eligibility states: `ELIGIBLE`, `WATCH`, `STAND_DOWN`, and `NO_DIRECTION`.
- Mission Control integration through the `DECISION_INTEGRITY` panel and drill-down.
- Read-only APIs for current-state evaluation, evidence health, and ad-hoc JSON evaluation.

## Canonical APIs

- `GET /api/decision-integrity/status`
- `GET /api/decision-integrity/current`
- `GET /api/decision-integrity/evidence-health`
- `POST /api/decision-integrity/evaluate`

## Safety

- No broker order submission.
- No production confidence mutation.
- No automatic strategy promotion.
- No market-state recomputation.
- Advisory-only, deterministic, and read-only.
