from __future__ import annotations
import json
from pathlib import Path
from engine.tick_momentum_feed import probe_futures_trade_access

ROOT=Path(__file__).resolve().parents[1]

def _env(status=403, payload=None):
    return {"__apex_provider_response__":True,"payload":payload,"diagnostics":{"provider_http_status":status,"provider_content_type":"application/json","provider_response_bytes":55,"provider_response_kind":"JSON","provider_json_parse_error":None,"provider_error_code":"ERROR","provider_error_message":"not entitled","provider_request_host":"api.polygon.io"}}

def test_probe_classifies_entitlement_without_persistence_or_evidence():
    result=probe_futures_trade_access(lambda *a,**k:_env(),base_url="https://api.polygon.io",api_key="SECRET",ticker="ESU6",credential_source="MASSIVE_API_KEY")
    assert result["provider_http_status"]==403
    assert result["entitlement_state"]=="NOT_ENTITLED_OR_FORBIDDEN"
    assert result["diagnostic_probe_only"] is True
    assert result["evidence_ingestion_permitted"] is False
    assert result["state_persisted"] is False
    assert result["snapshots_persisted"] is False
    assert result["execution_authority"] is False
    assert result["production_effect"]=="NONE"
    assert "SECRET" not in json.dumps(result)

def test_probe_access_confirmation_still_accepts_zero_transactions():
    result=probe_futures_trade_access(lambda *a,**k:_env(200,{"status":"OK","results":[]}),base_url="https://api.polygon.io",api_key="k",ticker="ESU6")
    assert result["ok"] is True
    assert result["status"]=="ACCESS_CONFIRMED"
    assert result["transactions_accepted"]==0

def test_route_and_release_truth_registered():
    registry=(ROOT/'config/apex_capability_registry.yaml').read_text()
    assert '/api/tick-momentum/probe' in registry
    app=(ROOT/'app.py').read_text()
    assert 'app.config["APEX_TICK_MOMENTUM_DIAGNOSTIC_PROBE"] = _tick_momentum_diagnostic_probe' in app
    assert 'register_tick_momentum_routes(app)' in app
    manifest=json.loads((ROOT/'config/apex_release_manifest.json').read_text())
    assert manifest['apex_version']==manifest['semantic_version']==manifest['application_version']=='69.7.0'
    g=manifest['guardrails']
    assert g['tick_momentum_diagnostic_probe_outside_rth'] is True
    assert g['tick_momentum_diagnostic_probe_ingests_evidence'] is False
    assert g['tick_momentum_diagnostic_probe_persists_state'] is False
    assert g['tick_momentum_diagnostic_probe_changes_trade_decisions'] is False
    assert g['tick_momentum_diagnostic_probe_changes_execution_authority'] is False
