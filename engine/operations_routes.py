"""APEX 11.0D Operations Center and read-only operational checks.

This module intentionally observes rather than mutates.  Checks report PASS,
WARN, FAIL, DISABLED, or BLOCKED and never fabricate readiness for history-
dependent capabilities.
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from flask import jsonify, render_template, request

VERSION = "11.0D_OPERATIONS_CENTER"

_STATUS_RANK = {"PASS": 0, "DISABLED": 1, "BLOCKED": 2, "WARN": 3, "FAIL": 4}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(status: str, summary: str, **details: Any) -> Dict[str, Any]:
    return {"status": status, "summary": summary, "details": details}


def _overall(checks: Mapping[str, Mapping[str, Any]]) -> str:
    return max((str(v.get("status", "WARN")) for v in checks.values()),
               key=lambda s: _STATUS_RANK.get(s, 3), default="WARN")


def _routes(app) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (str(r.rule), r.endpoint)):
        methods = sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
        route = str(rule.rule)
        endpoint = str(rule.endpoint)
        if route.startswith("/static/"):
            category = "static"
        elif route.startswith("/api/system") or route == "/health":
            category = "system"
        elif "/broker/" in route or "/trade/" in route:
            category = "execution"
        elif "learning" in route or "calibration" in route:
            category = "learning"
        elif "replay" in route or "review" in route or "signal" in route:
            category = "review"
        elif "flow" in route:
            category = "flow"
        elif "feature_store" in route or "similarity" in route or "provenance" in route:
            category = "history"
        elif route.startswith("/api/"):
            category = "intelligence"
        else:
            category = "dashboard"
        rows.append({
            "route": route,
            "methods": methods,
            "endpoint": endpoint,
            "category": category,
            "auth_required": False,
            "description": endpoint.replace("_", " ").strip(),
            "dynamic": "<" in route,
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


def _route_group_check(app, title: str, routes: List[str], *, blocked_when_missing: bool = False) -> Dict[str, Any]:
    present = [r for r in routes if _route_exists(app, r)]
    missing = [r for r in routes if r not in present]
    if not missing:
        return _check("PASS", f"{title} routes are registered", present=present, missing=[])
    status = "BLOCKED" if blocked_when_missing and not present else "WARN"
    return _check(status, f"{len(present)}/{len(routes)} {title.lower()} routes are registered",
                  present=present, missing=missing)


def _all_checks(app) -> Dict[str, Dict[str, Any]]:
    checks: Dict[str, Dict[str, Any]] = {
        "application": _check("PASS", "Flask application is responding", version=VERSION,
                              route_count=len(list(app.url_map.iter_rules()))),
        "database": _database_check(),
        "data_freshness": _route_group_check(app, "Market-data health", ["/api/market_health", "/api/market_status"]),
        "providers": _providers_check(),
        "recommendation_ledger": _route_group_check(
            app, "Recommendation ledger",
            ["/api/recommendation-ledger/health", "/api/recommendation-ledger/coverage"],
            blocked_when_missing=True),
        "outcome_grader": _route_group_check(
            app, "Outcome grader",
            ["/api/recommendation-ledger/pending-grades", "/api/recommendation-ledger/grade-due"],
            blocked_when_missing=True),
        "chain_quality": _route_group_check(app, "Chain quality", ["/api/options_chain_intelligence", "/api/premium_strategy"]),
        "execution": _route_group_check(app, "Execution", ["/api/broker/etrade/status", "/api/trade/spx/preview-entry"]),
        "clock": _clock_check(),
        "version_consistency": _route_group_check(app, "Release management", ["/api/system/release", "/api/system/migrations", "/api/system/integrity"]),
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
        "calibration", "similarity", "learning-safety", "end-to-end", "alerts", "scheduler",
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
