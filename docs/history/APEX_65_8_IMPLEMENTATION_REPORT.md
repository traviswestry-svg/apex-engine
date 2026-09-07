# APEX 65.8 — Evidence Accumulation Observatory

## Pre-build conflict audit
APEX already contained: a shared learning maturity contract (`engine/learning_maturity.py`), LTPE maturity gating, governance history/maturity gating, HLCE automatic outcome grading/statistics, Phase 13 historical readiness, and Phase 31 evidence status/calibration surfaces. Building another learning/maturity engine would have duplicated and conflicted with those authorities.

## Build decision
65.8 was narrowed to the missing capability: one read-only cross-subsystem observatory that proves whether the existing evidence stores are accumulating and identifies the first blocked HLCE lifecycle stage.

## Added
- `engine/evidence_accumulation_observatory.py`
- `engine/evidence_accumulation_routes.py`
- `GET /api/learning/evidence-readiness`
- `GET /api/learning/evidence-readiness/health`
- tests proving read-only behavior, lifecycle detection, and cross-store cold/accumulating state.

## Explicit non-goals / conflict prevention
65.8 does not create evidence, grade outcomes, alter thresholds, backfill history, calculate a competing probability, change canonical decisions, or affect execution. Existing HLCE, LTPE, governance, research, similarity, evidence, and market-memory engines remain authoritative for their own domains.

## Backfill decision
No automatic backfill was added. Historical reconstruction should be a separately reviewed build because each source must be proven point-in-time reconstructable before insertion; 65.8 only makes the need and current evidence coverage visible.
