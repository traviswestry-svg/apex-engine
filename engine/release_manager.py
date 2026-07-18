"""APEX release metadata and deployment visibility.

Read-only contracts used to identify exactly what code and capabilities are
running in an environment. No endpoint in this module changes trading state.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

RELEASE_VERSION = "10.0.2"
RELEASE_NAME = "RELEASE_MANAGER"
APP_VERSION = f"{RELEASE_VERSION}_{RELEASE_NAME}"
DATABASE_SCHEMA_VERSION = "5"

FEATURES: List[str] = [
    "Institutional State",
    "Evidence Graph",
    "Decision Trace",
    "Market Story",
    "Quality Gating",
    "Decision Provenance",
    "Historical Similarity",
    "Learning Calibration",
    "Dashboard Evidence",
    "Production Observability",
    "Market Status",
    "Release Manager",
]


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _git_commit() -> str | None:
    supplied = _env_first("APEX_GIT_COMMIT", "RENDER_GIT_COMMIT", "GIT_COMMIT", "SOURCE_VERSION")
    if supplied:
        return supplied[:40]
    try:
        root = Path(__file__).resolve().parents[1]
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=1
        ).strip()
        return value[:40] or None
    except Exception:
        return None


def _build_id() -> str:
    return _env_first("APEX_BUILD_ID", "RENDER_DEPLOY_ID", "RENDER_SERVICE_ID") or "local-or-unknown"


def _deployed_at() -> str | None:
    return _env_first("APEX_DEPLOYED_AT", "RENDER_DEPLOY_CREATED_AT")


def migration_status() -> Dict[str, Any]:
    configured = _env_first("APEX_DATABASE_SCHEMA_VERSION") or DATABASE_SCHEMA_VERSION
    required = DATABASE_SCHEMA_VERSION
    pending = [] if configured == required else [f"database schema {configured} -> {required}"]
    return {
        "database_version": configured,
        "required_database_version": required,
        "pending_migrations": pending,
        "ready": not pending,
    }


def release_metadata() -> Dict[str, Any]:
    migrations = migration_status()
    return {
        "version": RELEASE_VERSION,
        "application_version": APP_VERSION,
        "release_name": RELEASE_NAME,
        "build": _build_id(),
        "commit": _git_commit(),
        "deployed_at": _deployed_at(),
        "reported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": _env_first("APEX_ENVIRONMENT", "RENDER", "FLASK_ENV") or "unknown",
        "features": list(FEATURES),
        **migrations,
        "guardrails": {
            "read_only": True,
            "changes_trade_decisions": False,
            "exposes_secrets": False,
        },
    }
