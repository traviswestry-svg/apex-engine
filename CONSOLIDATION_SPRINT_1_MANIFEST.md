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
