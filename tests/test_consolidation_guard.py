"""Consolidation Sprint 1 guard — keeps the codebase from regrowing sprawl.

Three enforcement layers:
  1. Modules deleted in Sprint 1 stay deleted.
  2. Versioned-filename FREEZE: no NEW engine module may carry a version suffix
     (_v250, _v26x, ...). Versioning belongs in git history, not filenames. The
     existing inventory is grandfathered verbatim; additions fail.
  3. Dead-module detector: the same static import-graph reachability analysis
     that drove Sprint 1 runs on every test run. An engine module reachable
     from no runtime root and imported by no test is dead code and fails here
     the day it is introduced — not two years later in an audit.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DELETED_IN_SPRINT_1 = [
    "engine/cache.py", "engine/confidence.py", "engine/format.py",
    "engine/institutional_command_center_v245.py",
    "engine/institutional_command_center_v245_routes.py",
    "engine/logging.py", "engine/market_regime.py", "engine/math.py",
    "engine/recommendation_ledger_routes.py", "engine/ribbon.py",
    "engine/risk.py", "engine/scheduler.py", "engine/structure.py",
    "engine/trend.py", "engine/types.py",
    "engine/director/test_active_trade_director.py",
]

RUNTIME_ROOTS = ["app", "wsgi", "scanner_worker", "signal_evaluator",
                 "flatfiles_ingest", "flatfiles_probe",
                 "engine.application_composition"]

# Modules with no runtime path that tests deliberately exercise. Shrink this
# list in later sprints; never grow it without a reason recorded in the
# consolidation manifest.
TEST_ONLY_ALLOWLIST = {
    "engine.canonical_decision",
    "engine.outcome_grader",
}

_VERSION_SUFFIX = re.compile(r"_v\d")


def _modules():
    mods = {}
    for p in ROOT.glob("*.py"):
        mods[p.stem] = p
    for p in ROOT.glob("engine/**/*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(ROOT).with_suffix("")
        mods[".".join(rel.parts)] = p
    return mods


def _imports_of(path: Path, mods) -> set:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                m = node.module
                if node.level:
                    base = ".".join(path.relative_to(ROOT).with_suffix("").parts[:-node.level])
                    m = f"{base}.{m}" if base else m
                out.add(m)
                for a in node.names:
                    out.add(f"{m}.{a.name}")
            elif node.level:
                base = ".".join(path.relative_to(ROOT).with_suffix("").parts[:-node.level])
                for a in node.names:
                    out.add(f"{base}.{a.name}")
    return {i for i in out if i in mods}


def test_sprint1_deletions_stay_deleted():
    back = [f for f in DELETED_IN_SPRINT_1 if (ROOT / f).exists()]
    assert not back, (
        f"{back} deleted in Consolidation Sprint 1 (dead code — imported by "
        f"nothing) has been reintroduced. If the functionality is needed, put "
        f"it in a canonical live module, not a resurrected file."
    )


def test_versioned_filename_freeze():
    grandfathered = {
        # Frozen inventory at Sprint 1. Do NOT add to this list — new work goes
        # into canonical unversioned modules; git carries the version history.
        p.name for p in [
            *(ROOT / "engine").glob("*_v*.py"),
        ] if _VERSION_SUFFIX.search(p.name)
    }
    # The set above is computed live, so this test asserts the FROZEN COUNT:
    # additions raise the count and fail; deletions (consolidation) lower it
    # and the ceiling ratchets down via the recorded number below.
    FROZEN_MAX = 48  # ratcheted down in Sprint 2 (was 49 at Sprint 1)
    current = len(grandfathered)
    assert current <= FROZEN_MAX, (
        f"{current} versioned engine filenames (> frozen max {FROZEN_MAX}). "
        f"A new *_v<digits>* module was added. Version in git, not filenames: "
        f"extend the canonical module instead."
    )


def test_no_dead_engine_modules():
    mods = _modules()
    graph = {name: _imports_of(p, mods) for name, p in mods.items()}

    reach = set()
    stack = [r for r in RUNTIME_ROOTS if r in mods]
    while stack:
        n = stack.pop()
        if n in reach:
            continue
        reach.add(n)
        stack.extend(graph.get(n, ()))

    test_reach = set()
    stack = []
    for t in [*ROOT.glob("tests/*.py"), *ROOT.glob("templates/test_*.py")]:
        stack.extend(_imports_of(t, mods))
    while stack:
        n = stack.pop()
        if n in test_reach:
            continue
        test_reach.add(n)
        stack.extend(graph.get(n, ()))

    engine_mods = {m for m in mods if m.startswith("engine.")
                   and not m.endswith("__init__")}
    dead = sorted(m for m in engine_mods
                  if m not in reach and m not in test_reach)
    assert not dead, (
        f"Dead engine modules (unreachable from every runtime root, imported "
        f"by no test): {dead}. Wire them in or delete them — dead code is not "
        f"allowed to accumulate."
    )

    test_only = {m for m in engine_mods if m not in reach and m in test_reach}
    unexpected = sorted(test_only - TEST_ONLY_ALLOWLIST)
    assert not unexpected, (
        f"New test-only engine modules (no runtime path): {unexpected}. Either "
        f"wire them into the runtime or add to TEST_ONLY_ALLOWLIST with a "
        f"manifest entry explaining why."
    )
