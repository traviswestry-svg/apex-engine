"""Read-only APEX release-manager API routes."""
from __future__ import annotations

from flask import jsonify

from .release_manager import FEATURES, APP_VERSION, migration_status, release_metadata


def register_release_routes(app) -> None:
    @app.get('/api/system/version')
    def _system_version():
        metadata = release_metadata()
        return jsonify({
            'ok': True,
            'version': metadata['version'],
            'application_version': metadata['application_version'],
            'release_name': metadata['release_name'],
        })

    @app.get('/api/system/build')
    def _system_build():
        metadata = release_metadata()
        return jsonify({'ok': True, 'build': {
            'build': metadata['build'],
            'commit': metadata['commit'],
            'deployed_at': metadata['deployed_at'],
            'reported_at': metadata['reported_at'],
            'environment': metadata['environment'],
        }, 'version': APP_VERSION})

    @app.get('/api/system/features')
    def _system_features():
        return jsonify({'ok': True, 'features': list(FEATURES), 'count': len(FEATURES), 'version': APP_VERSION})

    @app.get('/api/system/migrations')
    def _system_migrations():
        status = migration_status()
        return jsonify({'ok': True, 'migrations': status, 'version': APP_VERSION}), (200 if status['ready'] else 503)

    @app.get('/api/system/release')
    def _system_release():
        return jsonify({'ok': True, 'release': release_metadata(), 'version': APP_VERSION})
