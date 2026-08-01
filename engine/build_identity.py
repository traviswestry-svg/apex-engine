"""APEX 65.6.5 — canonical version/build identity.

This module separates three concepts that historically shared a generic
``version`` field:

* runtime_release_version: canonical deployed APEX product release
* component_version: version of the engine/subsystem producing a payload
* stabilization_build: active production-stabilization build

It is metadata-only and must never affect trading, scoring, routing, or broker
behavior.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from engine.release_manager import APPLICATION_VERSION as RUNTIME_RELEASE_VERSION

STABILIZATION_BUILD = "65.6.5"
IDENTITY_SCHEMA_VERSION = "65.6.5"


def build_identity(
    *,
    component_name: str,
    component_version: Optional[str] = None,
    runtime_release_version: Optional[str] = None,
) -> Dict[str, Any]:
    runtime_version = str(runtime_release_version or RUNTIME_RELEASE_VERSION)
    comp_version = str(component_version or runtime_version)
    return {
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        "runtime_release_version": runtime_version,
        "component_name": str(component_name),
        "component_version": comp_version,
        "stabilization_build": STABILIZATION_BUILD,
    }


def apply_build_identity(
    payload: Dict[str, Any],
    *,
    component_name: str,
    component_version: Optional[str] = None,
    runtime_release_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Add explicit identity fields while preserving legacy ``version`` keys."""
    identity = build_identity(
        component_name=component_name,
        component_version=component_version,
        runtime_release_version=runtime_release_version,
    )
    payload["build_identity"] = identity
    payload["runtime_release_version"] = identity["runtime_release_version"]
    payload["component_version"] = identity["component_version"]
    payload["stabilization_build"] = identity["stabilization_build"]
    return payload
