"""APEX 65.3 — canonical runtime and engine dependency map.

Static repository introspection only: no network I/O, database access, scanner
work, or trading-engine execution. The result is cached per process and can be
served safely during market hours.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"

MONDAY_CRITICAL = {
    "app",
    "engine.market_state",
    "engine.institutional_intelligence",
    "engine.gamma",
    "engine.auction_intelligence",
    "engine.dealer_positioning",
    "engine.flow_intelligence",
    "engine.options_chain",
    "engine.volatility",
    "engine.execution_intelligence",
    "engine.trade_director_market_memory",
    "engine.trade_director_cross_asset",
    "engine.trade_director_strategy_orchestration",
}

FEED_TOKENS = {
    "polygon": ("polygon", "massive.com", "api.polygon"),
    "quantdata": ("quantdata",),
    "benzinga": ("benzinga",),
    "telegram": ("telegram", "send_telegram"),
    "etrade": ("etrade", "e*trade"),
    "tradingview": ("tv_signal", "tradingview"),
}

COMPAT_MARKERS = ("legacy", "compat", "roadmap", "deprecated", "shim")
ROUTE_RE = re.compile(r"['\"](/(?:api|tv_signal)[^'\"\s]*)['\"]")


def _module_name(path: Path) -> Optional[str]:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return None
    if path.suffix != ".py":
        return None
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _python_files() -> List[Path]:
    # Include all top-level runtime/support Python modules, not only app/wsgi/scanner.
    # APEX 65.3 under-counted dependencies reachable through apex_engines.py and
    # other root support modules, which could create false ORPHANED labels.
    files = [p for p in sorted(ROOT.glob("*.py")) if not p.name.startswith("test_")]
    files.extend(sorted(ENGINE.rglob("*.py")))
    return [p for p in files if p.exists() and "__pycache__" not in p.parts]


def _imports(path: Path) -> Set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError):
        return set()
    out: Set[str] = set()
    current = _module_name(path) or ""
    package = current.rsplit(".", 1)[0] if "." in current else ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                pkg_parts = package.split(".") if package else []
                keep = max(0, len(pkg_parts) - node.level + 1)
                prefix = ".".join(pkg_parts[:keep])
                base = f"{prefix}.{base}".strip(".")
            if base:
                out.add(base)
                for alias in node.names:
                    if alias.name != "*":
                        out.add(f"{base}.{alias.name}")
    return out


def _resolve_repo_module(name: str, modules: Set[str]) -> Optional[str]:
    candidate = name
    while candidate:
        if candidate in modules:
            return candidate
        candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
    return None


def _route_declarations(path: Path) -> List[Dict[str, Any]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError):
        return []
    rows: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            method = dec.func.attr.lower()
            if method not in {"get", "post", "put", "patch", "delete", "route"}:
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant) or not isinstance(dec.args[0].value, str):
                continue
            route = dec.args[0].value
            methods = [method.upper()] if method != "route" else ["GET"]
            if method == "route":
                for kw in dec.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        vals = [e.value for e in kw.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                        if vals:
                            methods = [v.upper() for v in vals]
            rows.append({"path": route, "methods": methods, "handler": node.name})
    return rows


def _dashboard_consumers() -> Dict[str, Set[str]]:
    consumers: Dict[str, Set[str]] = {}
    roots = [ROOT / "static", ROOT / "templates"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".js", ".html"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            rel = str(path.relative_to(ROOT))
            for route in ROUTE_RE.findall(text):
                clean = route.split("?", 1)[0]
                consumers.setdefault(clean, set()).add(rel)
    return consumers


def _feeds(text: str) -> List[str]:
    low = text.lower()
    return sorted(name for name, tokens in FEED_TOKENS.items() if any(tok in low for tok in tokens))


def _reachable(graph: Mapping[str, Set[str]], roots: Iterable[str]) -> Set[str]:
    seen: Set[str] = set()
    stack = [r for r in roots if r in graph]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(graph.get(cur, set()) - seen)
    return seen


def _classification(module: str, *, reachable: bool, incoming: int, routes: int, text: str) -> str:
    low = f"{module} {text[:1200]}".lower()
    if any(marker in low for marker in COMPAT_MARKERS):
        return "COMPATIBILITY" if reachable or routes else "DORMANT"
    if reachable:
        return "ACTIVE"
    if routes or incoming:
        return "DORMANT"
    return "ORPHANED"


@lru_cache(maxsize=1)
def build_dependency_map() -> Dict[str, Any]:
    files = _python_files()
    module_paths = {_module_name(p): p for p in files if _module_name(p)}
    modules = set(module_paths)
    graph: Dict[str, Set[str]] = {m: set() for m in modules}
    incoming: Dict[str, int] = {m: 0 for m in modules}
    route_rows: List[Dict[str, Any]] = []
    consumers = _dashboard_consumers()

    for mod, path in module_paths.items():
        for imp in _imports(path):
            resolved = _resolve_repo_module(imp, modules)
            if resolved and resolved != mod:
                graph[mod].add(resolved)
        for rr in _route_declarations(path):
            rr = dict(rr)
            rr["module"] = mod
            rr["file"] = str(path.relative_to(ROOT))
            rr["dashboard_consumers"] = sorted(consumers.get(rr["path"], set()))
            route_rows.append(rr)
    for deps in graph.values():
        for dep in deps:
            incoming[dep] += 1

    runtime_roots = [m for m in ("app", "wsgi", "scanner_worker") if m in modules]
    active = _reachable(graph, runtime_roots)

    engine_rows: List[Dict[str, Any]] = []
    for mod in sorted(m for m in modules if m.startswith("engine.")):
        path = module_paths[mod]
        text = path.read_text(encoding="utf-8", errors="ignore")
        owned_routes = [r for r in route_rows if r["module"] == mod]
        classification = _classification(
            mod, reachable=mod in active, incoming=incoming[mod], routes=len(owned_routes), text=text
        )
        engine_rows.append({
            "module": mod,
            "file": str(path.relative_to(ROOT)),
            "classification": classification,
            "monday_critical": mod in MONDAY_CRITICAL,
            "feeds": _feeds(text),
            "imports": sorted(graph[mod]),
            "imported_by_count": incoming[mod],
            "route_count": len(owned_routes),
            "routes": [{"path": r["path"], "methods": r["methods"], "dashboard_consumers": r["dashboard_consumers"]} for r in owned_routes],
        })

    counts: Dict[str, int] = {}
    for row in engine_rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    critical_rows = [r for r in engine_rows if r["monday_critical"]]
    critical_missing = sorted(MONDAY_CRITICAL - {"app"} - {r["module"] for r in critical_rows})
    critical_not_active = sorted(r["module"] for r in critical_rows if r["classification"] != "ACTIVE")

    feed_map: Dict[str, List[str]] = {}
    for row in engine_rows:
        for feed in row["feeds"]:
            feed_map.setdefault(feed, []).append(row["module"])

    route_rows.sort(key=lambda r: (r["path"], ",".join(r["methods"]), r["module"]))

    # Operational Monday path. These are explicit contracts rather than inferred
    # guesses: they represent the production decision flow we expect to remain
    # stable while the underlying module graph evolves.
    decision_specs = [
        ("signal_ingest", "TradingView / Pine", ["tradingview"], ["app"], "/tv_signal"),
        ("institutional_composition", "Institutional OS composition", ["polygon", "quantdata", "benzinga"], ["engine.market_state", "engine.institutional_intelligence"], "/api/institutional_os"),
        ("market_memory", "Trade Director Market Memory", [], ["engine.trade_director_market_memory"], "/api/position/market-memory"),
        ("cross_asset", "Trade Director Cross-Asset Intelligence", ["polygon", "quantdata"], ["engine.trade_director_cross_asset"], "/api/position/cross-asset-intelligence"),
        ("strategy_orchestration", "Trade Director Strategy Orchestration", [], ["engine.trade_director_strategy_orchestration"], "/api/position/strategy-orchestration"),
        ("evidence", "Institutional Evidence / Readiness", [], ["app"], "/api/evidence/status"),
        ("execution", "SPX execution gateway", ["etrade"], ["app"], "/api/trade/spx/place-entry"),
    ]
    decision_path = []
    for order, (stage, label, feeds, stage_modules, route) in enumerate(decision_specs, start=1):
        owners = sorted({r["module"] for r in route_rows if r["path"] == route})
        decision_path.append({
            "order": order, "stage": stage, "label": label, "feeds": feeds,
            "engines": stage_modules, "route": route, "route_owners": owners,
            "dashboard_consumers": sorted(consumers.get(route, set())),
        })

    cleanup_candidates = [
        {
            "module": r["module"], "file": r["file"],
            "classification": r["classification"],
            "disposition": ("REVIEW_FOR_REMOVAL" if r["classification"] == "ORPHANED" else "REVIEW_AND_CONSOLIDATE"),
            "imported_by_count": r["imported_by_count"], "route_count": r["route_count"],
        }
        for r in engine_rows if r["classification"] != "ACTIVE"
    ]

    digest_source = json.dumps({
        "engines": [(r["module"], r["classification"], r["imports"], [x["path"] for x in r["routes"]]) for r in engine_rows],
        "routes": [(r["path"], r["methods"], r["module"]) for r in route_rows],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")

    return {
        "ok": not critical_missing and not critical_not_active,
        "status": "HEALTHY" if not critical_missing and not critical_not_active else "DEGRADED",
        "schema_version": "65.4",
        "architecture_hash": hashlib.sha256(digest_source).hexdigest()[:16],
        "runtime_roots": runtime_roots,
        "summary": {
            "engine_modules": len(engine_rows),
            "route_declarations": len(route_rows),
            "dashboard_route_references": len(consumers),
            "classifications": counts,
            "monday_critical_total": len(critical_rows),
            "monday_critical_missing": critical_missing,
            "monday_critical_not_active": critical_not_active,
        },
        "feed_map": {k: sorted(v) for k, v in sorted(feed_map.items())},
        "monday_critical": critical_rows,
        "monday_decision_path": decision_path,
        "cleanup_candidates": cleanup_candidates,
        "engines": engine_rows,
        "routes": route_rows,
    }


def clear_dependency_map_cache() -> None:
    build_dependency_map.cache_clear()
