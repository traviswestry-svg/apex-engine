# Consolidation Sprint 1 — Dead Module Removal + Anti-Regrowth Guard

## Method
Static import graph over app.py, wsgi.py, scanner_worker.py, signal_evaluator.py,
flatfiles_*, engine/**, tests/**, templates/test_*. A module is DEAD only if it is
unreachable from every runtime root AND imported by no test. Every candidate was
additionally grep-verified against string/dynamic references before deletion.

## Deleted (16 files, ~61 KB)
Dead re-export shims (relics of the original apex_engines dedup):
  engine/confidence.py  engine/market_regime.py  engine/ribbon.py
  engine/risk.py        engine/structure.py      engine/trend.py
Dead utility modules (superseded, imported by nothing):
  engine/cache.py  engine/format.py  engine/logging.py  engine/math.py
  engine/scheduler.py  engine/types.py
Dead feature modules:
  engine/institutional_command_center_v245.py        (+ its routes file)
  engine/institutional_command_center_v245_routes.py
  engine/recommendation_ledger_routes.py             (ledger engine itself remains live)
Duplicate test (byte-identical to tests/ copy; never collected — testpaths=["tests"]):
  engine/director/test_active_trade_director.py

## Kept deliberately
Test-only modules (no runtime path, but tests exercise them — candidates for a
later sprint, not deletions): engine/canonical_decision.py,
engine/outcome_grader.py, engine/trade_director_decision_quality.py

## Guard added
tests/test_consolidation_guard.py
  1. Deleted modules stay deleted.
  2. Versioned filename FREEZE: no NEW engine/*_v<digits>*.py beyond the
     grandfathered inventory. Versioning belongs in git, not filenames.
  3. Dead-module detector: the same reachability analysis runs in CI; any
     future engine module imported by nothing fails the suite.

## Validation
Full suite green after removal (run pytest; see test count in ARCHITECTURE.md).

---

# Consolidation Sprint 2 — Decision Family (executed 2026-07-26)

## Deleted (7 files) / Created (2)
- engine/decision_routes.py                              → absorbed into engine/decision_intelligence.py
- engine/institutional_decision_engine_v20.py            ┐ merged into engine/institutional_decision_engine.py (NEW)
- engine/institutional_decision_engine_routes.py         ┘
- engine/trade_director_decision_intelligence.py         ┐
- engine/trade_director_institutional_decision_engine.py ├ merged into engine/trade_director_decision.py (NEW)
- engine/trade_director_decision_quality.py              ┘
- engine/decision_narrative.py                           → absorbed into engine/premium_discipline.py

## Renamed
- tests/test_institutional_decision_engine_v20.py → tests/test_institutional_decision_engine.py

## Repointed imports
app.py (3 blocks), 5 engine modules (workspace_v212, replay_lab_v202,
execution_optimizer_v201, strategy_intelligence_v203, trading_brain_v230),
premium_discipline_routes.py, 4 test files.

## Guard ratchet
FROZEN_MAX 49 → 48 (institutional_decision_engine_v20 unversioned).
TEST_ONLY_ALLOWLIST: trade_director_decision_quality removed (now runtime).

## Vetoes (see CONSOLIDATION_MERGE_MAP.md for detail)
decision_intelligence_center (circular import), decision_review (store
dependency on a contract module), v250/v252/v254 trio (v250 is a nine-importer
hub with dynamic string imports — rescoped to Sprint 3).

## Validation
Full suite 1,514 passed / 0 failed. Boot smoke: 812 routes; /api/decision and
/api/institutional-decision/* return 200 with unchanged payloads.
