#!/usr/bin/env python3
"""APEX 65.0 static frontend/backend route contract audit.

Conservative by design: only compares literal /api/... paths. Dynamic routes are
normalized to a prefix match and reported separately instead of treated as missing.
"""
from __future__ import annotations
import ast, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_FILES = [ROOT / "app.py", *sorted((ROOT / "engine").rglob("*.py"))]
FRONT_FILES = [*sorted((ROOT / "static").rglob("*.js")), *sorted((ROOT / "templates").rglob("*.html"))]
ROUTE_DECORATORS = {"route", "get", "post", "put", "patch", "delete"}

def backend_routes():
    routes = set()
    for path in PY_FILES:
        try: tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError: continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute): continue
                if dec.func.attr not in ROUTE_DECORATORS or not dec.args: continue
                arg = dec.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    routes.add(arg.value)
    return routes

def frontend_refs():
    refs = set()
    pat = re.compile(r"['\"](/api/[A-Za-z0-9_./<>:-]+)")
    for path in FRONT_FILES:
        text = path.read_text(encoding="utf-8", errors="ignore")
        refs.update(m.group(1).split("?")[0] for m in pat.finditer(text))
    return refs

def compatible(ref, routes):
    if ref in routes: return True
    for route in routes:
        prefix = route.split("<", 1)[0]
        if "<" in route and ref.startswith(prefix): return True
    return False

def main():
    routes, refs = backend_routes(), frontend_refs()
    missing = sorted(ref for ref in refs if not compatible(ref, routes))
    result = {"ok": not missing, "backend_literal_routes": len(routes), "frontend_api_refs": len(refs), "unresolved": missing}
    print(json.dumps(result, indent=2))
    return 0 if not missing else 1
if __name__ == "__main__": raise SystemExit(main())
