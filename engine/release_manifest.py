"""APEX 47.0.1 — canonical release manifest and capability registry."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .release_manager import APP_VERSION, RELEASE_MANIFEST

VERSION = APP_VERSION
BUILD_NAME = str(RELEASE_MANIFEST.get("build_name") or "Canonical Version Unification")
SCHEMA_VERSION = "apex.release_manifest.v1"
ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "apex_capability_registry.yaml"


def _registry_text() -> str:
    try: return REGISTRY_PATH.read_text(encoding="utf-8")
    except OSError: return ""


def _parse_registry_minimal(text: str) -> dict[str, Any]:
    # Avoid adding a PyYAML runtime dependency. The raw registry remains canonical;
    # this parser extracts capability names/status/version for diagnostics.
    caps: dict[str, Any] = {}
    current = None
    in_caps = False
    for raw in text.splitlines():
        if raw.strip() == "capabilities:": in_caps = True; continue
        if not in_caps: continue
        if raw.startswith("  ") and not raw.startswith("    ") and raw.strip().endswith(":"):
            current = raw.strip()[:-1]; caps[current] = {}; continue
        if current and raw.startswith("    ") and ":" in raw:
            key, value = raw.strip().split(":", 1)
            if key in {"status", "version", "canonical_module", "decision_authority"}:
                caps[current][key] = value.strip().strip("'\"")
    return caps


def manifest() -> dict[str, Any]:
    text = _registry_text()
    caps = _parse_registry_minimal(text)
    return {
        "ok": True, "schema_version": SCHEMA_VERSION, "apex_version": VERSION,
        "build_name": BUILD_NAME,
        "build_hash": os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "unavailable",
        "deployed_at": os.getenv("RENDER_DEPLOY_TIMESTAMP") or os.getenv("DEPLOYED_AT") or None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "application_entrypoint": "wsgi.py", "canonical_app": "app.py",
        "registry_path": "config/apex_capability_registry.yaml",
        "active_capabilities": sorted(k for k,v in caps.items() if v.get("status") == "active"),
        "shadow_capabilities": sorted(k for k,v in caps.items() if v.get("status") == "shadow"),
        "deprecated_capabilities": sorted(k for k,v in caps.items() if v.get("status") in {"deprecated","quarantined"}),
        "capabilities": caps,
        "execution_authority": False,
    }
