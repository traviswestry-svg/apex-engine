# Consolidation Merge Map — Sprints 2–4

> Built from the measured import graph (2026-07-26), not from filenames.
> Rules for every merge, no exceptions:
> 1. **Route paths never change.** The dashboard and any external callers keep
>    working. Routes move between modules; URLs are frozen.
> 2. **One merge per deploy.** Move code → run full suite → deploy → verify →
>    next merge. Never batch merges.
> 3. **Ratchet the guard.** Every absorbed `*_v###.py` lowers `FROZEN_MAX` in
>    tests/test_consolidation_guard.py. The ceiling only goes down.
> 4. **Tests move with code.** The absorbed module's tests are folded into the
>    anchor's test file in the same change.
> 5. Before each merge, re-verify the wiring live (grep + import graph) — this
>    map is a plan, not a substitute for looking.

## Sprint 2 — DECISION family: 22 modules → 4

**Anchors (survive):**
- `decision_intelligence.py` — the 7.5.7 six-question panel. THE live decision
  read; everything display-facing folds toward it.
- `institutional_decision_object.py` — the shared decision data contract
  (4 engine importers). Stays the single schema.
- `decision_evidence_pipeline.py` — the 48.2 evidence bridge (live via
  recommendation_ledger).
- `engine/director/` package — untouched; it is already well-factored.

**Absorb (engine+routes pairs collapse to one module each, then fold):**
- `decision_routes.py` → into `decision_intelligence.py` (1 route).
- `institutional_decision_engine_v20.py` + `institutional_decision_engine_routes.py`
  → `institutional_decision_engine.py` (unversioned). 6 engine importers keep
  working via this one canonical name.
- `decision_intelligence_center.py` + `decision_intelligence_core.py`
  → fold into `decision_intelligence.py`; verify wiring first (importer scan
  showed no direct engine importers — confirm how app reaches them before
  moving, per rule 5).
- `trade_director_decision_intelligence.py`,
  `trade_director_institutional_decision_engine.py`,
  `trade_director_decision_quality.py` (test-only) → one
  `trade_director_decision.py`.
- `decision_narrative.py`, `decision_provenance.py`, `decision_review.py`
  → into `institutional_decision_object.py` as the contract's narrative /
  provenance / review views (their importers are route modules; imports
  repoint in the same change).
- `canonical_decision.py` (test-only, 0 importers) → merge into
  `decision_evidence_pipeline.py` or delete with its tests if redundant.

**Park (shadow-mode, data-gated per BACKLOG — do NOT merge yet):**
- `decision_outcome_forecast_v252(+_routes)` — 31KB, zero engine importers,
  shadow-mode. Collapse engine+routes into one file, unversion the name, and
  leave it alone until graded-outcome data exists to justify it. If the data
  gate hasn't cleared by the time Sprint 4 finishes, delete it — the git
  history keeps it recoverable.
- `institutional_decision_integrity_v250(+_routes)` — same treatment.
- `institutional_decision_review_v254(+_routes)` — 33KB advisory-only; same.

## Sprint 3 — CONFIDENCE/CALIBRATION family: 10 → 3

**Anchors:**
- `learning_calibration.py` — most-imported calibration module (3 engine
  importers incl. dashboard_evidence). Canonical outcome-calibration home.
- `confidence_attribution.py` — imported by apex_engines itself; canonical
  attribution home. Absorb `confidence_attribution_engine.py` (near-duplicate
  by name and purpose; verify overlap, keep the superset).
- `continuous_learning_calibration_v234.py` → rename unversioned
  `continuous_learning_calibration.py` (4 importers repoint) OR fold into
  `learning_calibration.py` if the overlap is high — decide by diff, not name.

**Absorb:**
- `prediction_confidence_calibration.py` (0 importers — check how app reaches
  it; likely a dashboard template route) → `learning_calibration.py`.
- `adaptive_confidence_calibration_v253(+_routes)` — shadow-mode; collapse
  pair, unversion, park behind its data gate like the v25x decision modules.
- `adaptive_portfolio_calibration.py`, `adaptive_refusal_calibration.py`
  → keep; imported by premium_discipline_routes and distinct in purpose. Not
  every similarly-named module is a duplicate — these earn their files.
- `trade_director_performance_calibration.py` → into
  `trade_director_decision.py` from Sprint 2.

## Sprint 4 — LEARNING family: 10 → 3

**Anchors:** `adaptive_learning.py` (imported by canonical_decision +
outcome_grader), `trade_director_institutional_learning.py` (4 importers —
rename `trade_director_learning_core.py` after absorbing
`trade_director_learning.py`), `learning_calibration.py` (shared with Sprint 3).

**Absorb:** `adaptive_learning_engine_v2.py` (2KB shim-sized) →
`adaptive_learning.py`; `institutional_learning_engine.py` →
`learning_calibration.py`; `learning_routes.py` + `continuous_learning_routes.py`
→ their anchors; `market_replay_learning_lab_v202.py` (1KB) → wherever its one
importer (institutional_decision_suite_routes) lands in Sprint 2.

## End state
Decision/confidence/learning: 42 modules → ~10 canonical + parked shadow
modules with explicit data-gate deadlines. FROZEN_MAX ratchets 49 → ~38.
After Sprint 4: same exercise for the `institutional_*` (19.x–26.x) route
suites, which is where most of the remaining 44 versioned filenames live.
