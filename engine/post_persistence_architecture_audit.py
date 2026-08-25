"""APEX 67.9.1 — Post-Persistence Architecture Audit.

Read-only static architecture diagnostic for the staged canonical-persistence program.
It inventories remaining direct SQLite usage after 67.8.1 and highlights places where
persistence policy or decision-adjacent state still deserves review. It never mutates
source, databases, runtime state, decisions, risk, or execution authority.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from .architecture_integrity import snapshot as architecture_snapshot

VERSION = "69.4.2"
SCHEMA_VERSION = "apex.post_persistence_architecture_audit.v2"
ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
MANIFEST = ROOT / "config" / "apex_release_manifest.json"

# Explicit consequence classification is intentionally conservative. These are not
# claims of execution authority; they are review priority based on proximity to
# decision, risk, execution, market-state, eligibility, or canonical state flows.
HIGH_CONSEQUENCE_MODULES = {
    "app.py",
    "live_operations.py",
    "premium_strategy_routes.py",
    "trade_director_change_control.py",
    "institutional_autonomous_desk.py",
    "premium_discipline.py",
    "decision_outcome_forecast.py",
    "adaptive_portfolio_calibration.py",
    "trade_director_data_lineage.py",
    "institutional_market_state_engine.py",
    "confidence_attribution_engine.py",
    "institutional_order_flow_intelligence.py",
    "level_transition_probability.py",
    "feature_store_db.py",
}

INFRASTRUCTURE_MODULES = {
    "db_resilience.py",
    "persistent_store.py",
    "release_manager.py",
    "institutional_release_manager.py",
    "canary_deployment.py",
    "sandbox_execution_validation.py",
    "operations_routes.py",
    "profile_history.py",
    "shadow_validation.py",
}

SPECIALIZED_OBSERVATIONAL_BUFFER_MODULES = {
    "market_microstructure_store.py",
}

SPECIALIZED_PERSISTENCE_POLICY = {
    "market_microstructure_store.py": {
        "classification": "SPECIALIZED_OBSERVATIONAL_BUFFER",
        "canonical_high_consequence_persistence_required": False,
        "direct_sqlite_exception_approved": True,
        "high_consequence_state": False,
        "decision_authority": "NONE",
        "execution_authority": "NONE",
        "production_effect": "NONE",
    }
}

LOWER_AUTHORITY_MODULES = {
    "explainable_intelligence_assistant.py",
    "institutional_playbook_engine.py",
    "trade_director_mobile_momentum_alerts.py",
    "async_narrative.py",
    "cross_examination_engine.py",
    "institutional_ai_trading_coach_v235.py",
    "portfolio_outcome_attribution.py",
    "market_memory_engine_v220.py",
    "market_narrative.py",
    "performance_intelligence.py",
    "strategy_discovery_engine.py",
}

_DIRECT_CONNECT_RE = re.compile(r"\bsqlite3\.connect\s*\(")
_POLICY_RE = re.compile(r"PRAGMA\s+(?:journal_mode|busy_timeout|foreign_keys|synchronous)", re.I)


def _function_for_line(tree: ast.AST, lineno: int) -> str | None:
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start)
            if start <= lineno <= end:
                span = end - start
                if best is None or span < best[0]:
                    best = (span, node.name)
    return best[1] if best else None


def _classify(name: str) -> str:
    if name in SPECIALIZED_OBSERVATIONAL_BUFFER_MODULES:
        return "SPECIALIZED_OBSERVATIONAL_BUFFER"
    if name in HIGH_CONSEQUENCE_MODULES:
        return "HIGH_CONSEQUENCE_REVIEW"
    if name in INFRASTRUCTURE_MODULES:
        return "INFRASTRUCTURE_REVIEW"
    if name in LOWER_AUTHORITY_MODULES:
        return "LOWER_AUTHORITY_REVIEW"
    return "UNCLASSIFIED_REVIEW"


def _inventory_direct_sqlite() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    audit_paths = list(ENGINE.rglob("*.py")) + [ROOT / "app.py"]
    for path in sorted(audit_paths):
        if path.name in {"canonical_persistence.py", Path(__file__).name}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text)
        except Exception:
            tree = ast.Module(body=[], type_ignores=[])
        lines = text.splitlines() if 'text' in locals() else []
        for lineno, line in enumerate(lines, 1):
            matches = list(_DIRECT_CONNECT_RE.finditer(line))
            if not matches:
                continue
            rel = str(path.relative_to(ROOT))
            context = "\n".join(lines[max(0, lineno - 8): min(len(lines), lineno + 8)])
            for occurrence, _match in enumerate(matches, 1):
                policy = SPECIALIZED_PERSISTENCE_POLICY.get(path.name)
                rows.append({
                    "module": rel,
                    "file": path.name,
                    "line": lineno,
                    "occurrence_on_line": occurrence,
                    "function": _function_for_line(tree, lineno),
                    "tier": _classify(path.name),
                    "explicit_policy_nearby": bool(_POLICY_RE.search(context)),
                    "specialized_persistence": dict(policy) if policy else None,
                    "source_excerpt": line.strip()[:240],
                })
    return rows


def _competing_policy_sites(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Direct connection sites with local SQLite policy are priority consolidation candidates."""
    return [
        {
            "module": row["module"],
            "line": row["line"],
            "function": row["function"],
            "tier": row["tier"],
        }
        for row in rows
        if row["explicit_policy_nearby"]
    ]


def snapshot() -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    architecture = architecture_snapshot()
    rows = _inventory_direct_sqlite()
    by_tier: dict[str, list[str]] = {}
    for row in rows:
        by_tier.setdefault(row["tier"], []).append(row["module"])
    by_tier = {k: sorted(set(v)) for k, v in sorted(by_tier.items())}
    high = by_tier.get("HIGH_CONSEQUENCE_REVIEW", [])
    competing = _competing_policy_sites(rows)

    persistence_state = "CLOSED" if not rows else ("HIGH_CONSEQUENCE_REMAINS" if high else "LOWER_PRIORITY_REMAINS")
    status = "HEALTHY" if architecture.get("ok") else "DEGRADED"
    return {
        "ok": status == "HEALTHY",
        "status": status,
        "audit_state": persistence_state,
        "apex_version": manifest.get("apex_version"),
        "build_name": manifest.get("build_name"),
        "audit_version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "decision_authority": "NONE",
        "execution_authority": "NONE",
        "read_only": True,
        "audit_scope": ["engine/**/*.py", "app.py"],
        "architecture_integrity": {
            "status": architecture.get("status"),
            "identity_aligned": architecture.get("identity_aligned"),
            "missing_module_count": len(architecture.get("missing_modules") or []),
            "duplicate_route_count": len(architecture.get("duplicate_routes") or []),
            "duplicate_routes": architecture.get("duplicate_routes") or [],
            "duplicate_route_details": architecture.get("duplicate_route_details") or [],
            "cleanup_violation_count": len(architecture.get("cleanup_violations") or []),
        },
        "persistence": {
            "remaining_direct_sqlite_files": len({r["module"] for r in rows}),
            "remaining_direct_sqlite_calls": len(rows),
            "high_consequence_file_count": len(high),
            "competing_policy_site_count": len(competing),
            "by_tier": by_tier,
            "direct_sqlite_sites": rows,
            "competing_policy_sites": competing,
            "approved_specialized_observational_buffers": [
                {"module": row["module"], **row["specialized_persistence"]}
                for row in rows if row.get("specialized_persistence")
            ],
        },
        "findings": [
            {
                "severity": "HIGH" if high else "INFO",
                "code": "DIRECT_SQLITE_HIGH_CONSEQUENCE" if high else "DIRECT_SQLITE_REMAINS",
                "detail": (
                    f"{len(high)} high-consequence module(s) still contain direct sqlite3.connect() usage."
                    if high else
                    f"{len({r['module'] for r in rows})} lower-priority module(s) still contain direct sqlite3.connect() usage."
                ),
            },
            {
                "severity": "MEDIUM" if competing else "INFO",
                "code": "LOCAL_SQLITE_POLICY_REMAINS",
                "detail": f"{len(competing)} direct connection site(s) appear to carry local SQLite PRAGMA policy near the connection.",
            },
        ],
        "recommended_next_action": (
            "Review and stage only the remaining high-consequence persistence sites; do not mass-replace lower-authority or specialized connections."
            if high else
            "Persistence is sufficiently closed for a shift toward effectiveness, decision coherence, and execution reliability; retain only justified specialized connections."
        ),
    }
