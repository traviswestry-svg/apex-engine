"""APEX 67.2.0 — Architecture Closure & Registry Integrity."""
from __future__ import annotations
import importlib.util
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

def _route_inventory() -> tuple[int,list[str]]:
    route_re=re.compile(r'@(?:app|bp|blueprint)\.route\(\s*["\']([^"\']+)["\']')
    seen={}
    duplicates=[]
    count=0
    for p in ROOT.rglob("*.py"):
        if "tests" in p.parts: continue
        if any(d in p.parts for d in FORBIDDEN_EXECUTABLE_ARTIFACT_DIRS): continue
        try: text=p.read_text(errors="ignore")
        except Exception: continue
        for route in route_re.findall(text):
            count+=1
            if route in seen:
                duplicates.append(route)
            else:
                seen[route]=str(p.relative_to(ROOT))
    return count,sorted(set(duplicates))

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
    route_count,dupes=_route_inventory()
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
        "cleanup_violations": cleanup,
        "engine_version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "decision_authority": "NONE",
        "execution_authority": "NONE",
    }
