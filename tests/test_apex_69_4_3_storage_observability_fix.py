from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_identity_stays_three_part_and_preserves_69_4_3_or_later():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    version = manifest["apex_version"]
    parts = tuple(int(x) for x in version.split("."))
    assert len(parts) == 3
    assert parts >= (69, 4, 3)
    assert manifest["semantic_version"] == version
    assert manifest["application_version"] == version


def test_storage_audit_route_is_registered_read_only_and_authenticated_by_global_layer():
    source = (ROOT / "app.py").read_text()
    assert '@app.get("/api/admin/storage/audit")' in source
    assert 'payload = dict(apex_storage_retention_audit())' in source
    assert '"read_only"] = True' in source
    assert '"maintenance_applied"] = False' in source
    # Auth is application-wide and installed before route registration.
    assert 'install_auth(app)' in source
    assert source.index('install_auth(app)') < source.index('@app.get("/api/admin/storage/audit")')


def test_endpoint_source_does_not_call_storage_mutators():
    source = (ROOT / "app.py").read_text()
    start = source.index('def api_admin_storage_audit():')
    end = source.index('@app.get("/api/runtime/health")', start)
    block = source[start:end]
    for forbidden in (
        'prune_mature_price_samples(',
        'cleanup_quarantined_backups(',
        'checkpoint_wals(',
        '.unlink(',
        'DELETE FROM',
    ):
        assert forbidden not in block


def test_release_manifest_preserves_storage_endpoint_truth():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    g = manifest["storage_retention_guardrails"]
    assert g["storage_audit_endpoint"] == "/api/admin/storage/audit"
    assert g["storage_audit_endpoint_read_only"] is True
    assert g["storage_audit_endpoint_authenticated"] is True
    assert g["storage_audit_endpoint_applies_maintenance"] is False
    assert g["storage_audit_endpoint_vacuum_performed"] is False
    assert g["canonical_evidence_delete"] is False


def test_capability_registry_accounts_for_storage_audit_route():
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert 'governed_storage_retention:' in registry
    assert 'routes: [/api/admin/storage/audit]' in registry
    assert 'route_access: application_wide_authenticated' in registry
    assert 'storage_audit_endpoint_read_only' in registry
    assert 'storage_audit_endpoint_does_not_invoke_maintenance' in registry
