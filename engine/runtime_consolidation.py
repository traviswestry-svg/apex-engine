"""APEX 65.5 backend runtime consolidation audit.

This module is intentionally read-only.  It performs a second-level audit over
65.3 dependency-map cleanup candidates so a static "ORPHANED" label is never
mistaken for permission to delete code.  It checks source, tests, configuration,
package semantics, route ownership and known dynamic-loading risk.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List
import re

from engine.runtime_dependency_map import build_dependency_map

ROOT = Path(__file__).resolve().parents[1]

# Files/locations that are not production import roots but still establish a
# contract that makes removal unsafe without a migration.
REFERENCE_ROOTS = (
    ROOT / "tests",
    ROOT / "config",
    ROOT / "apex_engines.py",
    ROOT / "scanner_worker.py",
    ROOT / "signal_evaluator.py",
    ROOT / "wsgi.py",
    ROOT / "app.py",
)

PACKAGE_SENTINELS = {"__init__.py"}
TEST_NAME_RE = re.compile(r"(^|/)test_[^/]+\.py$")


def _text_references(module: str, file_path: str) -> List[Dict[str, Any]]:
    """Find explicit references outside the candidate file itself.

    This is deliberately conservative: a hit means RETAIN/REVIEW, not proof the
    reference is executed in production.
    """
    tokens = {module, module.rsplit(".", 1)[-1]}
    hits: List[Dict[str, Any]] = []
    candidate = (ROOT / file_path).resolve()

    roots: List[Path] = []
    for root in REFERENCE_ROOTS:
        if root.is_file():
            roots.append(root)
        elif root.exists():
            roots.extend(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".py", ".yaml", ".yml", ".json", ".toml"})

    seen = set()
    for path in roots:
        try:
            if path.resolve() == candidate:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        matched = [tok for tok in tokens if tok and tok in text]
        if not matched:
            continue
        rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        if rel in seen:
            continue
        seen.add(rel)
        hits.append({"file": rel, "tokens": sorted(matched)})
    return sorted(hits, key=lambda row: row["file"])


def _disposition(candidate: Dict[str, Any], references: List[Dict[str, Any]]) -> Dict[str, Any]:
    file_path = str(candidate.get("file") or "")
    classification = str(candidate.get("classification") or "")
    route_count = int(candidate.get("route_count") or 0)
    incoming = int(candidate.get("imported_by_count") or 0)
    name = Path(file_path).name

    if name in PACKAGE_SENTINELS:
        return {"action": "RETAIN_PACKAGE_SENTINEL", "safe_to_delete": False,
                "reason": "Package initializer; static zero-import count is not deletion evidence."}
    if TEST_NAME_RE.search(file_path):
        return {"action": "MOVE_TO_TESTS", "safe_to_delete": False,
                "reason": "Test module is misplaced inside the runtime package; move before removing original."}
    if route_count:
        return {"action": "CONSOLIDATE_ROUTE_OWNER", "safe_to_delete": False,
                "reason": f"Owns {route_count} route declaration(s); requires route migration first."}
    if classification in {"COMPATIBILITY", "DORMANT"}:
        return {"action": "REVIEW_AND_CONSOLIDATE", "safe_to_delete": False,
                "reason": "Compatibility/dormant classification requires explicit migration or registrar removal."}
    if references:
        return {"action": "RETAIN_REFERENCED", "safe_to_delete": False,
                "reason": "Referenced by tests/config/root runtime support files outside the static engine graph."}
    if incoming:
        return {"action": "RETAIN_IMPORTED", "safe_to_delete": False,
                "reason": "Has incoming repository imports."}
    return {"action": "REVIEW_FOR_REMOVAL", "safe_to_delete": False,
            "reason": "No static runtime/test/config references found; manual dynamic-import and persistence review still required."}


@lru_cache(maxsize=1)
def build_consolidation_audit() -> Dict[str, Any]:
    dep = build_dependency_map()
    rows: List[Dict[str, Any]] = []
    for candidate in dep.get("cleanup_candidates", []):
        refs = _text_references(candidate["module"], candidate["file"])
        decision = _disposition(candidate, refs)
        rows.append({**candidate, **decision, "external_references": refs,
                     "external_reference_count": len(refs)})

    actions: Dict[str, int] = {}
    for row in rows:
        actions[row["action"]] = actions.get(row["action"], 0) + 1

    unsafe = [r["module"] for r in rows if r["action"] in {"CONSOLIDATE_ROUTE_OWNER", "RETAIN_REFERENCED", "RETAIN_IMPORTED", "RETAIN_PACKAGE_SENTINEL"}]
    move_only = [r["module"] for r in rows if r["action"] == "MOVE_TO_TESTS"]
    review = [r["module"] for r in rows if r["action"] == "REVIEW_FOR_REMOVAL"]

    return {
        "ok": True,
        "status": "HEALTHY",
        "schema_version": "65.5",
        "summary": {
            "candidate_count": len(rows),
            "actions": dict(sorted(actions.items())),
            "protected_or_migration_required": len(unsafe),
            "move_only": len(move_only),
            "manual_removal_review": len(review),
            "automatic_deletions": 0,
        },
        "policy": {
            "automatic_deletions": False,
            "rule": "No module is deleted from a static orphan label alone.",
        },
        "protected_modules": sorted(unsafe),
        "move_candidates": sorted(move_only),
        "manual_removal_review": sorted(review),
        "candidates": rows,
    }


def clear_consolidation_audit_cache() -> None:
    build_consolidation_audit.cache_clear()
