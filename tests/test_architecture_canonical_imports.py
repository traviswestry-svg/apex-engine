"""
Architecture guard (Tier 1, item 3).

WHY THIS EXISTS
---------------
A duplicate module (two copies of the same file at different paths) is a silent
hazard: edits and tests can target one copy while production imports the other.
This is exactly how a real Active Trade Director bug hid behind a passing test —
`pytest tests/` ran one copy of the director test while the failing copy lived
under engine/director/ and was never in the default run.

These tests fail loudly if:
  1. A known-canonical production module can't be imported from its canonical path.
  2. A top-level engine/X.py reappears as engine/<subpkg>/X.py (ambiguous duplicate).
  3. The full test suite and the tests/ subset diverge in a way that could hide
     a failing nested test (documents the discovery gap).
"""
import importlib
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

# Canonical import paths for production modules that previously had duplicates.
CANONICAL_MODULES = [
    "apex_engines",                              # root — imported by engine/*.py
    "engine.brokers.etrade_adapter",
    "engine.execution.broker_interface",
    "engine.execution.trade_risk_guard",
    "engine.execution.price_mapper",
    "engine.execution.trade_audit",
    "engine.execution.trade_routes",
    "engine.execution.bracket_manager",
    "engine.range_intelligence",
    "engine.confluence",
    "engine.event_calendar",
    "engine.decision_intelligence",
    "engine.director.director",
    "engine.director.persistence",
    "engine.director.contracts",
]


@pytest.mark.parametrize("modpath", CANONICAL_MODULES)
def test_canonical_module_imports(modpath):
    """Every canonical production module must import from its declared path."""
    importlib.import_module(modpath)


def test_no_toplevel_engine_duplicate_of_subpackage_module():
    """A top-level engine/X.py must not duplicate an engine/<subpkg>/X.py.

    (Package __init__.py files are exempt — they are legitimate, not duplicates.)
    """
    engine = REPO / "engine"
    top_level = {p.name for p in engine.glob("*.py") if p.name != "__init__.py"}
    duplicates = []
    for name in top_level:
        for sub in engine.iterdir():
            if sub.is_dir() and (sub / name).exists():
                duplicates.append(f"engine/{name} duplicates engine/{sub.name}/{name}")
    assert not duplicates, "Ambiguous duplicate modules found:\n" + "\n".join(duplicates)


def test_no_duplicate_test_files_across_trees():
    """The same test filename must not exist in both tests/ and engine/**/.

    A duplicated test file is how a failing test can hide from `pytest tests/`.
    """
    tests_dir = REPO / "tests"
    test_names = {p.name for p in tests_dir.glob("test_*.py")}
    stray = []
    for p in REPO.glob("engine/**/test_*.py"):
        if p.name in test_names:
            stray.append(f"{p.relative_to(REPO)} duplicates tests/{p.name}")
    # This is currently a KNOWN condition (engine/director/test_active_trade_director.py).
    # We assert it's tracked, not silently ignored: if you remove the stray copy,
    # update this list. Fail only on NEW, untracked duplicates.
    known = {"engine/director/test_active_trade_director.py duplicates tests/test_active_trade_director.py"}
    new = set(stray) - known
    assert not new, "New duplicate test files (can hide failures):\n" + "\n".join(new)
