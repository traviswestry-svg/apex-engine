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


# ── Director core-type ownership guard (APEX 9 Step 1) ──────────────────────
# WHY: the filename guard above only catches a fork that reuses the FILENAME.
# engine/contracts.py + engine/persistence.py were exactly that — an orphaned
# fork of the director's core types, imported by nothing, which silently held an
# unmerged fix ("position truth overrides debounce") while the live director kept
# emitting ENTER_CALL over a live position. A re-fork under any OTHER filename
# would slip past the name check, so ownership is asserted on the TYPES.
DIRECTOR_CORE_TYPES = [
    "Directive",
    "DirectorContext",
    "HoldLevel",
    "PositionView",
    "ConflictReport",
    "FlowAcceleration",
    "DirectivePersistence",
]

# Files permitted to define the director's core types (the canonical subpackage).
_DIRECTOR_TYPE_OWNERS = {
    "engine/director/contracts.py": {
        "Directive", "DirectorContext", "HoldLevel", "PositionView",
        "ConflictReport", "FlowAcceleration",
    },
    "engine/director/persistence.py": {"DirectivePersistence"},
}


def _definitions_of(type_name: str):
    """Every .py file in the repo that defines `class <type_name>`."""
    import re
    hits = []
    pattern = re.compile(rf"^class {re.escape(type_name)}\b", re.M)
    for path in REPO.rglob("*.py"):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(path.relative_to(REPO)))
        except OSError:
            continue
    return hits


@pytest.mark.parametrize("type_name", DIRECTOR_CORE_TYPES)
def test_director_core_type_defined_once_in_canonical_location(type_name):
    """Each director core type must be defined exactly once, inside engine/director/.

    Fails if a fork reintroduces a competing definition anywhere else — under any
    filename. This is the guard that engine/contracts.py would have tripped.
    """
    definitions = _definitions_of(type_name)
    allowed = [f for f, types in _DIRECTOR_TYPE_OWNERS.items() if type_name in types]
    assert definitions, f"{type_name} is not defined anywhere — expected in {allowed}"
    assert len(definitions) == 1, (
        f"{type_name} is defined in {len(definitions)} places: {definitions}\n"
        f"The director's core types must live only in {allowed}. A second "
        f"definition is a fork — edits and tests can target one copy while "
        f"production imports the other."
    )
    assert definitions[0] in allowed, (
        f"{type_name} is defined in {definitions[0]}, expected {allowed}"
    )


def test_orphaned_director_fork_stays_deleted():
    """engine/contracts.py and engine/persistence.py must not come back.

    They were an orphaned fork of engine/director/{contracts,persistence}.py with
    zero importers. Their one unique contribution — ENTRY_DIRECTIVES and the
    position-truth debounce bypass — is merged into the canonical modules.
    """
    for gone in ("engine/contracts.py", "engine/persistence.py"):
        assert not (REPO / gone).exists(), (
            f"{gone} is back. It duplicates engine/director/ core types. "
            f"Extend the director subpackage instead of forking it."
        )


def test_entry_directives_live_in_canonical_contracts():
    """The merged fix must stay wired: ENTRY_DIRECTIVES owned by director/contracts."""
    from engine.director.contracts import ENTRY_DIRECTIVES
    assert "ENTER_CALL" in ENTRY_DIRECTIVES and "ENTER_PUT" in ENTRY_DIRECTIVES
    # persistence must consume it — this is what stops ENTER over a live position
    src = (REPO / "engine/director/persistence.py").read_text()
    assert "ENTRY_DIRECTIVES" in src, (
        "director/persistence.py no longer imports ENTRY_DIRECTIVES — the "
        "position-truth-overrides-debounce fix has been unwired."
    )
