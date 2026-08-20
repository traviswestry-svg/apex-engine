"""APEX 67.2.0 — Architecture Closure & Registry Integrity."""
from __future__ import annotations
import importlib.util
import ast
import json
import re
from pathlib import Path
from typing import Any

VERSION="67.2.0"
SCHEMA_VERSION="apex.architecture_integrity.v1"
ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/"config"/"apex_release_manifest.json"
REGISTRY=ROOT/"config"/"apex_capability_registry.yaml"
FORBIDDEN_EXECUTABLE_ARTIFACT_DIRS={
    "_check","_ds_seg","_loi_seg","APEX_66_4_1_Decision_Coherence_Fix_Changed_Files"
}

def _registry_entries() -> dict[str,dict[str,Any]]:
    lines=REGISTRY.read_text(encoding="utf-8").splitlines()
    out: dict[str,dict[str,Any]]={}
    current=None
    in_caps=False
    for line in lines:
        if line.strip()=="capabilities:":
            in_caps=True; continue
        if not in_caps: continue
        m=re.match(r"^  ([A-Za-z0-9_]+):\s*$",line)
        if m:
            current=m.group(1); out[current]={}; continue
        if current:
            m=re.match(r"^    ([A-Za-z0-9_]+):\s*(.*?)\s*$",line)
            if m:
                k,v=m.groups()
                out[current][k]=v.strip().strip("'\"")
    return out

def _module_exists(module: str) -> bool:
    if module=="engine.app":  # explicitly quarantined legacy alias
        return False
    if module=="app":
        return (ROOT/"app.py").exists()
    parts=module.split(".")
    py=ROOT.joinpath(*parts).with_suffix(".py")
    pkg=ROOT.joinpath(*parts,"__init__.py")
    return py.exists() or pkg.exists()

def _literal_http_methods(call: ast.Call) -> tuple[str, ...]:
    """Return effective declared methods for a Flask route decorator.

    Flask defaults route() to GET (with implicit HEAD/OPTIONS).  Integrity is
    interested in overlapping *declared* application methods, so implicit
    HEAD/OPTIONS are intentionally not expanded here.
    """
    for kw in call.keywords:
        if kw.arg != "methods":
            continue
        if isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
            methods: list[str] = []
            for item in kw.value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    methods.append(item.value.upper())
            return tuple(sorted(set(methods))) or ("GET",)
        # Dynamic method expressions cannot be proven disjoint statically.
        return ("*",)
    return ("GET",)


def _route_inventory() -> tuple[int, list[str], list[dict[str, Any]]]:
    """Inventory literal Flask route decorators without path-only false positives.

    A duplicate is a repeated literal path whose declared HTTP method sets overlap.
    Separate GET and POST handlers on the same path are therefore legitimate, while
    two GET handlers (or any dynamic/unresolved method registration) remain a
    duplicate-integrity violation.
    """
    seen: dict[str, list[dict[str, Any]]] = {}
    duplicates: list[str] = []
    details: list[dict[str, Any]] = []
    count = 0

    for p in ROOT.rglob("*.py"):
        if "tests" in p.parts:
            continue
        if any(d in p.parts for d in FORBIDDEN_EXECUTABLE_ARTIFACT_DIRS):
            continue
        try:
            text = p.read_text(errors="ignore")
            tree = ast.parse(text)
        except Exception:
            continue

        rel = str(p.relative_to(ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
                    continue
                if deco.func.attr != "route":
                    continue
                owner = deco.func.value
                if not isinstance(owner, ast.Name) or owner.id not in {"app", "bp", "blueprint"}:
                    continue
                if not deco.args or not isinstance(deco.args[0], ast.Constant) or not isinstance(deco.args[0].value, str):
                    continue

                route = deco.args[0].value
                methods = set(_literal_http_methods(deco))
                count += 1
                current = {
                    "route": route,
                    "methods": sorted(methods),
                    "module": rel,
                    "function": node.name,
                    "line": getattr(deco, "lineno", getattr(node, "lineno", None)),
                }

                for prior in seen.get(route, []):
                    prior_methods = set(prior["methods"])
                    overlap = bool(methods & prior_methods) or "*" in methods or "*" in prior_methods
                    if overlap:
                        duplicates.append(route)
                        details.append({
                            "route": route,
                            "overlapping_methods": sorted((methods & prior_methods) or methods or prior_methods),
                            "first": prior,
                            "duplicate": current,
                        })
                seen.setdefault(route, []).append(current)

    return count, sorted(set(duplicates)), details

def snapshot() -> dict[str,Any]:
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries=_registry_entries()
    registry_top=None
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        m=re.match(r"^apex_version:\s*(.+?)\s*$",line)
        if m:
            registry_top=m.group(1).strip().strip("'\""); break
    missing=[]
    for name,row in entries.items():
        mod=row.get("canonical_module")
        status=row.get("status")
        if mod and status!="quarantined" and not _module_exists(mod):
            missing.append({"capability":name,"canonical_module":mod})
    cleanup=[]
    for d in FORBIDDEN_EXECUTABLE_ARTIFACT_DIRS:
        p=ROOT/d
        if p.exists():
            py=[str(x.relative_to(ROOT)) for x in p.rglob("*.py")]
            if py: cleanup.extend(py)
    route_count,dupes,dupe_details=_route_inventory()
    identity_ok=registry_top==manifest.get("apex_version")
    status="HEALTHY" if identity_ok and not missing and not dupes and not cleanup else "DEGRADED"
    return {
        "ok": status=="HEALTHY",
        "status": status,
        "apex_version": manifest.get("apex_version"),
        "build_name": manifest.get("build_name"),
        "release_series": manifest.get("release_series"),
        "released_at": manifest.get("released_at"),
        "registry_version": registry_top,
        "identity_aligned": identity_ok,
        "capability_count": len(entries),
        "capabilities": entries,
        "missing_modules": missing,
        "declared_route_count": route_count,
        "duplicate_routes": dupes,
        "duplicate_route_details": dupe_details,
        "cleanup_violations": cleanup,
        "engine_version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "decision_authority": "NONE",
        "execution_authority": "NONE",
    }
