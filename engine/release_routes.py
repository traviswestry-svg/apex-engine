cat > engine/release_routes.py <<'PY'
from __future__ import annotations

from flask import jsonify

from engine.release_manager import get_release_metadata


def register_release_manager_routes(app) -> None:
    @app.get("/api/system/version")
    def system_version():
        data = get_release_metadata()
        return jsonify(
            {
                "version": data["version"],
                "application_version": data["application_version"],
            }
        )

    @app.get("/api/system/build")
    def system_build():
        data = get_release_metadata()
        return jsonify(
            {
                "build": data["build"],
                "commit": data["commit"],
                "environment": data["environment"],
                "generated_at": data["generated_at"],
            }
        )

    @app.get("/api/system/features")
    def system_features():
        data = get_release_metadata()
        return jsonify(
            {
                "features": data["features"],
                "feature_count": len(data["features"]),
            }
        )

    @app.get("/api/system/migrations")
    def system_migrations():
        data = get_release_metadata()
        return jsonify(
            {
                "database_version": data["database_version"],
                "pending_migrations": data["pending_migrations"],
                "migration_status": data["migration_status"],
            }
        )

    @app.get("/api/system/release")
    def system_release():
        return jsonify(get_release_metadata())
PY
