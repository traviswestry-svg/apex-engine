"""APEX 24.5 - Institutional Command Center.

A unified operational dashboard that assembles all sixteen institutional
subsystems into one canonical panel set with drill-down navigation. It reuses the
existing Mission Control 2.0 aggregation (`build_mission_control`) for fourteen of
the panels and adds Operational Health and System Diagnostics from the Release
Manager, so there is a single canonical operational surface rather than a parallel
dashboard.

Read-only / advisory: this module only reads and presents the state produced by
the underlying engines. It performs no market recalculation, places no orders,
and mutates nothing.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Optional

from .institutional_mission_control_v213 import build_mission_control
from . import release_manager

VERSION = "24.5.0_INSTITUTIONAL_COMMAND_CENTER"
SCHEMA_VERSION = "apex.command_center_v245.v1"

# Canonical panel order: (panel_id, title, mission_control_group_key, drilldown_key)
# The last two panels are synthesized from the Release Manager.
PANELS = (
    ("trading_brain", "Trading Brain", "TRADING_BRAIN", "trading_brain"),
    ("regime_intelligence", "Regime Intelligence", "REGIME_INTELLIGENCE", "regime_intelligence"),
    ("forecast_engine", "Forecast Engine", "INSTITUTIONAL_FORECAST", "institutional_forecast"),
    ("playbook_engine", "Playbook Engine", "INSTITUTIONAL_PLAYBOOKS", "institutional_playbooks"),
    ("trading_coach", "Trading Coach", "TRADING_COACH", "trading_coach"),
    ("execution_intelligence", "Execution Intelligence", "EXECUTION_INTELLIGENCE", "execution_intelligence"),
    ("portfolio_intelligence", "Portfolio Intelligence", "PORTFOLIO_INTELLIGENCE", "portfolio_intelligence"),
    ("replay_simulator", "Replay & Simulator", "REPLAY_SIMULATOR", "replay_simulator"),
    ("strategy_research", "Strategy Research", "STRATEGY_RESEARCH", "strategy_research"),
    ("multi_timeframe", "Multi-Timeframe Intelligence", "MULTI_TIMEFRAME", "multi_timeframe"),
    ("market_memory", "Market Memory", "MEMORY", "memory"),
    ("continuous_learning", "Continuous Learning", "LEARNING", "continuous_learning"),
    ("configuration_governance", "Configuration Governance", "CONFIGURATION", "configuration"),
    ("dependency_governance", "Dependency Governance", "DEPENDENCIES", "dependencies"),
    ("operational_health", "Operational Health", None, None),
    ("system_diagnostics", "System Diagnostics", None, None),
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _diagnostics() -> dict[str, Any]:
    """Release-manager derived operational health + system diagnostics."""
    try:
        metadata = release_manager.release_metadata()
    except Exception:
        metadata = {}
    try:
        migrations = release_manager.migration_status()
    except Exception:
        migrations = {}
    try:
        integrity = release_manager.data_integrity()
    except Exception:
        integrity = {}
    migrations_ok = bool(migrations.get("ok", migrations.get("up_to_date", True)))
    integrity_ok = bool(integrity.get("ok", integrity.get("intact", True)))
    health_state = "PASS" if (migrations_ok and integrity_ok) else "WARNING"
    return {
        "metadata": metadata, "migrations": migrations, "integrity": integrity,
        "operational_state": health_state,
        "diagnostics_state": "PASS" if integrity_ok else "WARNING",
    }


def build_command_center(last: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Assemble the unified 16-panel command center with drill-down navigation."""
    mc = build_mission_control(dict(last or {}))
    groups = mc.get("groups", {})
    drilldowns = dict(mc.get("drilldowns", {}))
    diag = _diagnostics()

    panels = []
    for panel_id, title, group_key, drill_key in PANELS:
        if panel_id == "operational_health":
            panels.append({"id": panel_id, "title": title, "state": diag["operational_state"],
                           "summary": f"migrations {'ok' if diag['migrations'].get('ok', True) else 'attention'} · "
                                      f"integrity {'ok' if diag['integrity'].get('ok', True) else 'attention'}",
                           "drilldown": "/api/system/migrations"})
            drilldowns["operational_health"] = "/api/system/migrations"
            continue
        if panel_id == "system_diagnostics":
            panels.append({"id": panel_id, "title": title, "state": diag["diagnostics_state"],
                           "summary": f"{diag['metadata'].get('application_version', VERSION)}",
                           "drilldown": "/api/system/integrity"})
            drilldowns["system_diagnostics"] = "/api/system/integrity"
            continue
        group = groups.get(group_key, {})
        panels.append({
            "id": panel_id, "title": title,
            "state": group.get("state", "UNKNOWN"),
            "summary": group.get("summary", ""),
            "drilldown": drilldowns.get(drill_key),
        })

    return {
        "ok": True, "status": "READY", "version": VERSION, "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "overall_state": mc.get("state", "UNKNOWN"),
        "panel_count": len(panels),
        "panels": panels,
        "drilldowns": drilldowns,
        "mission_control_version": mc.get("version"),
        "decision_banner": mc.get("decision_banner"),
        "read_only": True, "advisory_only": True, "production_effect": "NONE",
    }


def panel(panel_id: str, last: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Drill-down for a single panel: its state, drilldown link, and (when
    available) the Mission Control detail block for that subsystem."""
    pid = str(panel_id or "").strip().lower()
    spec = next((p for p in PANELS if p[0] == pid), None)
    if not spec:
        return {"ok": False, "status": "UNKNOWN_PANEL", "panel_id": pid,
                "available_panels": [p[0] for p in PANELS]}
    cc = build_command_center(last)
    entry = next((p for p in cc["panels"] if p["id"] == pid), None)
    mc = build_mission_control(dict(last or {}))
    detail = mc.get(pid) or mc.get(spec[3]) if spec[3] else None
    return {"ok": True, "status": "READY", "version": VERSION, "panel": entry,
            "detail": detail, "read_only": True, "production_effect": "NONE"}


def status() -> dict[str, Any]:
    return {
        "status": "READY", "engine": "INSTITUTIONAL_COMMAND_CENTER",
        "version": VERSION, "schema_version": SCHEMA_VERSION,
        "panel_ids": [p[0] for p in PANELS], "panel_count": len(PANELS),
        "read_only": True, "advisory_only": True,
        "broker_order_submission_enabled": False, "production_effect": "NONE",
    }
