from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


APPLICATION_VERSION = "10.0.2_RELEASE_MANAGER"
SEMANTIC_VERSION = "10.0.2"
DATABASE_VERSION = "5"

FEATURES = [
    "Institutional State",
    "Evidence Graph",
    "Decision Trace",
    "Market Story",
    "Dashboard Evidence",
    "Similarity Engine",
    "Learning Engine",
    "Production Readiness",
    "Market Status",
    "Release Manager",
]


def get_release_metadata() -> dict[str, Any]:
    commit = (
        os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("GIT_COMMIT")
        or os.getenv("SOURCE_VERSION")
        or "unknown"
    )

    build = (
        os.getenv("RENDER_DEPLOY_ID")
        or os.getenv("BUILD_ID")
        or datetime.now(timezone.utc).strftime("%Y.%m.%d.%H%M")
    )

    environment = (
        os.getenv("RENDER_SERVICE_NAME")
        or os.getenv("FLASK_ENV")
        or os.getenv("ENVIRONMENT")
        or "unknown"
    )

    return {
        "version": SEMANTIC_VERSION,
        "application_version": APPLICATION_VERSION,
        "build": build,
        "commit": commit,
        "environment": environment,
        "features": FEATURES,
        "database_version": DATABASE_VERSION,
        "pending_migrations": [],
        "migration_status": "CURRENT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

# Backward-compatible alias used by app.py
APP_VERSION = APPLICATION_VERSION
