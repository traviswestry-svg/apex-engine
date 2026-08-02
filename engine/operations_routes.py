"""APEX 11.0D Operations Center and read-only operational checks.

This module intentionally observes rather than mutates.  Checks report PASS,
WARN, FAIL, DISABLED, or BLOCKED and never fabricate readiness for history-
dependent capabilities.
"""
from __future__ import annotations

import inspect
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from flask import jsonify, render_template, request

from .release_manager import APP_VERSION

VERSION = APP_VERSION

_STATUS_RANK = {"PASS": 0, "DISABLED": 1, "BLOCKED": 2, "WARN": 3, "FAIL": 4}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(status: str, summary: str, **details: Any) -> Dict[str, Any]:
    return {"status": status, "summary": summary, "details": details}


def _overall(checks: Mapping[str, Mapping[str, Any]]) -> str:
    return max((str(v.get("status", "WARN")) for v in checks.values()),
               key=lambda s: _STATUS_RANK.get(s, 3), default="WARN")


def _capability_route_metadata() -> Dict[str, Dict[str, Any]]:
    """Return route metadata from the canonical capability registry.

    The release-manifest parser deliberately has no PyYAML dependency, so this
    lightweight reader extracts only fields needed by the Operations Center.
    """
    try:
        from .release_manifest import REGISTRY_PATH
        text = REGISTRY_PATH.read_text(encoding="utf-8")
    except Exception:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    current: Optional[str] = None
    fields: Dict[str, Any] = {}

    def flush() -> None:
        if not current:
            return
        routes = fields.get("api_routes", [])
        for route in routes:
            result[str(route)] = {
                "capability": current,
                "status": fields.get("status", "unregistered"),
                "version": fields.get("version"),
                "canonical_module": fields.get("canonical_module"),
                "decision_authority": fields.get("decision_authority", "unknown"),
            }

    for raw in text.splitlines():
        if raw.startswith("  ") and not raw.startswith("    ") and raw.strip().endswith(":"):
            flush()
            current = raw.strip()[:-1]
            fields = {}
            continue
        if current and raw.startswith("    ") and ":" in raw:
            key, value = raw.strip().split(":", 1)
            value = value.strip()
            if key == "api_routes":
                fields[key] = [x.strip().strip("'\"") for x in value.strip("[]").split(",") if x.strip()]
            elif key in {"status", "version", "canonical_module", "decision_authority"}:
                fields[key] = value.strip("'\"")
    flush()
    return result


def _category_for_route(route: str) -> str:
    if route.startswith("/static/"):
        return "static"
    if route.startswith("/api/system") or route in {"/health", "/api/version", "/api/release-manifest"}:
        return "system"
    if any(token in route for token in ("/broker/", "/trade/", "/execution")):
        return "execution"
    if any(token in route for token in ("learning", "calibration", "outcome-grader")):
        return "learning"
    if any(token in route for token in ("replay", "review", "signal", "ledger")):
        return "review"
    if "flow" in route or "liquidity" in route:
        return "flow"
    if any(token in route for token in ("feature_store", "similarity", "provenance", "evidence", "decision-snapshot")):
        return "history"
    if route.startswith("/api/"):
        return "intelligence"
    return "dashboard"


def _influence_class(route: str, status: str, decision_authority: str) -> str:
    """Make route existence distinct from production decision influence."""
    r = route.lower()
    st = str(status or "").lower()
    authority = str(decision_authority or "unknown").lower()
    if st in {"deprecated", "quarantined"}:
        return "DEPRECATED"
    if st == "shadow":
        return "SHADOW"
    if "/trade/" in r or "/execution-gate/execute" in r:
        return "EXECUTION_GATE"
    if "risk" in r or "kill-switch" in r:
        return "RISK_GATE"
    if authority in {"canonical", "decision", "authoritative"}:
        return "DECISION_CORE"
    if authority == "advisory":
        return "ADVISORY"
    if any(x in r for x in ("/learning", "/calibration", "/grader", "/memory")):
        return "LEARNING_PRODUCER"
    if r.startswith("/api/"):
        return "DIAGNOSTIC"
    return "UI_OR_STATIC"


def _routes(app) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    registry = _capability_route_metadata()
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (str(r.rule), r.endpoint)):
        methods = sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
        route = str(rule.rule)
        endpoint = str(rule.endpoint)
        view = app.view_functions.get(endpoint)
        owner_module = getattr(view, "__module__", "unknown") if view else "unknown"
        doc = inspect.getdoc(view) if view else None
        description = (doc.splitlines()[0].strip() if doc else endpoint.replace("_", " ").strip())
        cap = registry.get(route, {})
        auth_required = bool(
            getattr(view, "auth_required", False)
            or getattr(view, "login_required", False)
            or any(token in endpoint.lower() for token in ("oauth", "login", "callback"))
        )
        influence_class = _influence_class(route, cap.get("status", "active"), cap.get("decision_authority", "unknown"))
        rows.append({
            "route": route,
            "methods": methods,
            "endpoint": endpoint,
            "category": _category_for_route(route),
            "owner_module": cap.get("canonical_module") or owner_module,
            "runtime_module": owner_module,
            "capability": cap.get("capability"),
            "capability_version": cap.get("version"),
            "status": cap.get("status", "active" if not route.startswith("/static/") else "system"),
            "decision_authority": cap.get("decision_authority", "unknown"),
            "influence_class": influence_class,
            "influences_decision": influence_class == "DECISION_CORE",
            "can_reach_execution": influence_class in {"EXECUTION_GATE", "RISK_GATE"},
            "auth_required": auth_required,
            "description": description,
            "dynamic": "<" in route,
            "safe_probe": "GET" in methods and "<" not in route and not auth_required,
        })
    return rows


def _route_exists(app, route: str) -> bool:
    return any(str(rule.rule) == route for rule in app.url_map.iter_rules())


def _db_candidates() -> Iterable[Path]:
    seen = set()
    for key in ("DB_PATH", "SPINE_DB_PATH", "REVIEW_DB_PATH", "APEX_DB_PATH"):
        raw = os.getenv(key)
        if raw:
            p = Path(raw).expanduser()
            if p not in seen:
                seen.add(p)
                yield p
    for raw in ("apex_tracking.db", "apex_signals.db", "apex_reviews.db", "apex.db"):
        p = Path(raw)
        if p.exists() and p not in seen:
            seen.add(p)
            yield p


def _database_check() -> Dict[str, Any]:
    database_url = bool(os.getenv("DATABASE_URL"))
    files = []
    writable = True
    failures = []
    for path in _db_candidates():
        item = {"path": str(path), "exists": path.exists()}
        if path.exists():
            item["size_bytes"] = path.stat().st_size
            try:
                conn = sqlite3.connect(str(path), timeout=2)
                conn.execute("SELECT 1").fetchone()
                conn.close()
                item["readable"] = True
            except Exception as exc:
                item["readable"] = False
                failures.append(f"{path}: {exc}")
            item["writable"] = os.access(path, os.W_OK)
            writable = writable and item["writable"]
        files.append(item)
    if failures:
        return _check("FAIL", "One or more databases failed a read check", files=files, errors=failures)
    if database_url or files:
        return _check("PASS" if writable else "WARN", "Database storage is reachable",
                      database_url_configured=database_url, files=files, writable=writable)
    return _check("WARN", "No database storage was discovered", database_url_configured=False, files=[])


def _providers_check() -> Dict[str, Any]:
    providers = {
        "massive_polygon": bool(os.getenv("POLYGON_API_KEY") or os.getenv("MASSIVE_API_KEY")),
        "quantdata": bool(os.getenv("QUANTDATA_API_KEY")),
        "etrade": bool(os.getenv("ETRADE_CONSUMER_KEY") and os.getenv("ETRADE_CONSUMER_SECRET")),
        "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "tradingview_webhook": bool(os.getenv("TV_WEBHOOK_SECRET") or os.getenv("TRADINGVIEW_SECRET")),
    }
    configured = sum(1 for v in providers.values() if v)
    status = "PASS" if configured >= 2 else "WARN"
    return _check(status, f"{configured} provider integrations are configured", providers=providers)


def _clock_check() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    return _check("PASS", "Server clock is available", utc=now.isoformat(), epoch=now.timestamp(), timezone="UTC")




def _recommendation_ledger_check() -> Dict[str, Any]:
    try:
        from .recommendation_ledger import health as ledger_health, coverage as ledger_coverage, counts as ledger_counts
        health = ledger_health()
        coverage = ledger_coverage()
        counts = ledger_counts()
        if health.get("status") == "FAIL":
            return _check("FAIL", "Recommendation ledger is not writable", health=health, coverage=coverage, counts=counts)
        if counts.get("total", 0) == 0:
            return _check("BLOCKED", "Recommendation ledger is ready and waiting for live captures", health=health, coverage=coverage, counts=counts)
        if counts.get("gradeable", 0) == 0:
            return _check("BLOCKED", "Recommendation ledger is capturing records but has no executable outcomes yet", health=health, coverage=coverage, counts=counts)
        status = "PASS" if coverage.get("coverage_pct") == 100 else "WARN"
        return _check(status, "Recommendation ledger is capturing durable decision records", health=health, coverage=coverage, counts=counts)
    except Exception as exc:
        return _check("FAIL", "Recommendation ledger functional check failed", error=str(exc))


def _outcome_grader_check() -> Dict[str, Any]:
    try:
        from .recommendation_ledger import counts as ledger_counts, list_recommendations
        c = ledger_counts()
        pending = len(list_recommendations(limit=500, unresolved_only=True))
        if c.get("total", 0) == 0:
            return _check("BLOCKED", "Outcome grader is waiting for captured recommendations", pending=0)
        if pending:
            return _check("WARN", "Recommendations are awaiting executable close or settlement economics", pending=pending,
                          policy="No directional proxy grading")
        return _check("PASS", "All captured recommendations have terminal outcomes", pending=0)
    except Exception as exc:
        return _check("FAIL", "Outcome grader check failed", error=str(exc))

def _route_group_check(app, title: str, routes: List[str], *, blocked_when_missing: bool = False) -> Dict[str, Any]:
    present = [r for r in routes if _route_exists(app, r)]
    missing = [r for r in routes if r not in present]
    if not missing:
        return _check("PASS", f"{title} routes are registered", present=present, missing=[])
    status = "BLOCKED" if blocked_when_missing and not present else "WARN"
    return _check(status, f"{len(present)}/{len(routes)} {title.lower()} routes are registered",
                  present=present, missing=missing)




def _canonical_version_check(app) -> Dict[str, Any]:
    """Verify release endpoints agree with the canonical release manifest."""
    try:
        from .release_manifest import manifest
        expected = str(manifest().get("apex_version") or "")
        routes = ["/api/version", "/api/release-manifest", "/api/system/version", "/api/system/release"]
        observed: Dict[str, Any] = {}
        mismatches: Dict[str, Any] = {}
        with app.test_client() as client:
            for route in routes:
                if not _route_exists(app, route):
                    observed[route] = {"registered": False}
                    mismatches[route] = "missing"
                    continue
                response = client.get(route)
                payload = response.get_json(silent=True) or {}
                # Release identity is exposed by both flat release endpoints and
                # runtime-health payloads that nest it under ``deployment`` or
                # ``release``. Inspect those canonical containers rather than
                # falsely warning whenever a route uses a structured payload.
                containers = [payload]
                for key in ("deployment", "release", "metadata", "data"):
                    nested = payload.get(key)
                    if isinstance(nested, Mapping):
                        containers.append(nested)
                candidates: Dict[str, Any] = {}
                canonical_values: List[str] = []
                for index, container in enumerate(containers):
                    prefix = "root" if index == 0 else next(
                        (key for key in ("deployment", "release", "metadata", "data") if payload.get(key) is container),
                        f"nested_{index}",
                    )
                    for field in ("apex_version", "version", "application_version", "semantic_version"):
                        value = container.get(field)
                        candidates[f"{prefix}.{field}"] = value
                        if value not in (None, ""):
                            canonical_values.append(str(value))
                matches = expected in canonical_values
                observed[route] = {"http_status": response.status_code, "values": candidates, "matches": matches}
                if response.status_code >= 500 or not matches:
                    mismatches[route] = observed[route]
        if mismatches:
            return _check("WARN", "Release endpoints do not all report the canonical APEX version",
                          expected=expected, observed=observed, mismatches=mismatches)
        return _check("PASS", f"All release endpoints report APEX {expected}", expected=expected, observed=observed)
    except Exception as exc:
        return _check("FAIL", "Canonical version consistency check failed", error=str(exc))


def _evidence_pipeline_check() -> Dict[str, Any]:
    try:
        from .evidence_pipeline_trace import build_trace
        trace = build_trace()
        status_map = {"HEALTHY": "PASS", "COLLECTING": "WARN", "WAITING_FOR_LIVE_DATA": "BLOCKED", "FAIL": "FAIL"}
        first = trace.get("first_blocker") or {}
        summary = first.get("summary") or "Evidence pipeline is healthy"
        return _check(status_map.get(trace.get("status"), "WARN"), summary,
                      pipeline_status=trace.get("status"), totals=trace.get("totals"),
                      first_blocker=first, stages=trace.get("stages"))
    except Exception as exc:
        return _check("FAIL", "Evidence pipeline trace failed", error=str(exc))


def _all_checks(app) -> Dict[str, Dict[str, Any]]:
    checks: Dict[str, Dict[str, Any]] = {
        "application": _check("PASS", "Flask application is responding", version=VERSION,
                              route_count=len(list(app.url_map.iter_rules()))),
        "database": _database_check(),
        "data_freshness": _route_group_check(app, "Market-data health", ["/api/market_health", "/api/market_status"]),
        "providers": _providers_check(),
        "recommendation_ledger": _recommendation_ledger_check(),
        "outcome_grader": _outcome_grader_check(),
        "chain_quality": _route_group_check(app, "Chain quality", ["/api/options_chain_intelligence", "/api/premium_strategy"]),
        "execution": _route_group_check(app, "Execution", ["/api/broker/etrade/status", "/api/trade/spx/preview-entry"]),
        "clock": _clock_check(),
        "version_consistency": _canonical_version_check(app),
        "evidence_pipeline": _evidence_pipeline_check(),
        "calibration": _route_group_check(app, "Calibration", ["/api/learning/calibration", "/api/calibration/readiness"], blocked_when_missing=True),
        "similarity": _route_group_check(app, "Similarity", ["/api/feature_store/health", "/api/feature_store/coverage"], blocked_when_missing=True),
        "learning_safety": _route_group_check(app, "Learning safety", ["/api/learning/proposals", "/api/learning/apply"], blocked_when_missing=True),
        "end_to_end": _route_group_check(app, "Decision path", ["/api/market_state", "/api/decision", "/api/premium_strategy"]),
        "alerts": _check("PASS" if bool(os.getenv("TELEGRAM_BOT_TOKEN")) else "DISABLED",
                         "Alert transport configured" if os.getenv("TELEGRAM_BOT_TOKEN") else "Telegram alert transport is not configured"),
        "scheduler": _route_group_check(app, "Scheduler visibility", ["/api/system/metrics"]),
    }
    return checks


def register_operations_routes(app, **_kwargs) -> None:
    """Register Operations Center UI and read-only API inventory/check routes."""

    @app.get("/apex_os/operations")
    def _operations_center():
        return render_template("operations_center.html", version=VERSION)

    @app.get("/api/endpoints")
    def _endpoint_inventory():
        rows = _routes(app)
        category = (request.args.get("category") or "").strip().lower()
        query = (request.args.get("q") or "").strip().lower()
        if category:
            rows = [r for r in rows if r["category"] == category]
        if query:
            rows = [r for r in rows if query in r["route"].lower() or query in r["endpoint"].lower()]
        return jsonify({"ok": True, "version": VERSION, "count": len(rows), "endpoints": rows, "generated_at": _now()})

    @app.get("/api/endpoints/<category>")
    def _endpoint_inventory_category(category: str):
        rows = [r for r in _routes(app) if r["category"] == category.lower()]
        return jsonify({"ok": True, "version": VERSION, "category": category.lower(), "count": len(rows), "endpoints": rows})

    @app.get("/api/endpoints/search")
    def _endpoint_search():
        q = (request.args.get("q") or "").strip().lower()
        rows = [r for r in _routes(app) if q in r["route"].lower() or q in r["endpoint"].lower()]
        return jsonify({"ok": True, "query": q, "count": len(rows), "endpoints": rows})

    @app.get("/api/endpoints/stats")
    def _endpoint_stats():
        rows = _routes(app)
        by_category: Dict[str, int] = {}
        by_method: Dict[str, int] = {}
        for row in rows:
            by_category[row["category"]] = by_category.get(row["category"], 0) + 1
            for method in row["methods"]:
                by_method[method] = by_method.get(method, 0) + 1
        return jsonify({"ok": True, "version": VERSION, "total": len(rows),
                        "by_category": by_category, "by_method": by_method, "generated_at": _now()})

    @app.get("/api/endpoints/openapi")
    def _endpoint_openapi():
        paths: Dict[str, Any] = {}
        for row in _routes(app):
            paths.setdefault(row["route"], {})
            for method in row["methods"]:
                paths[row["route"]][method.lower()] = {
                    "summary": row["description"], "tags": [row["category"]],
                    "responses": {"200": {"description": "Successful response"}},
                }
        return jsonify({"openapi": "3.0.3", "info": {"title": "APEX API", "version": VERSION}, "paths": paths})


    @app.get("/api/evidence-pipeline/trace")
    def _evidence_pipeline_trace():
        from .evidence_pipeline_trace import build_trace
        return jsonify(build_trace())

    @app.get("/api/system/checks")
    def _checks_all():
        started = time.perf_counter()
        checks = _all_checks(app)
        return jsonify({"ok": True, "status": _overall(checks), "version": VERSION,
                        "generated_at": _now(), "duration_ms": round((time.perf_counter()-started)*1000, 2),
                        "checks": checks})

    check_names = {
        "application", "database", "data-freshness", "providers", "recommendation-ledger",
        "outcome-grader", "chain-quality", "execution", "clock", "version-consistency",
        "calibration", "similarity", "learning-safety", "end-to-end", "alerts", "scheduler", "evidence-pipeline",
    }

    @app.get("/api/system/checks/<name>")
    def _check_one(name: str):
        normalized = name.strip().lower()
        if normalized not in check_names:
            return jsonify({"ok": False, "error": "unknown_check", "available": sorted(check_names)}), 404
        key = normalized.replace("-", "_")
        checks = _all_checks(app)
        payload = checks[key]
        code = 503 if payload["status"] == "FAIL" else 200
        return jsonify({"ok": True, "name": normalized, "version": VERSION,
                        "generated_at": _now(), "check": payload}), code
