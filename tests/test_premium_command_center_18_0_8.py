import json

from flask import Flask

from engine.adaptive_refusal_calibration import CalibrationStore
from engine.premium_command_center import build_command_center, serialize_decision
from engine.premium_discipline import RefusalLedger
from engine.premium_discipline_routes import register_premium_discipline_routes


def test_serialize_decision_parses_ledger_json():
    row = {
        "id": 4, "strategy": "IRON_CONDOR", "decision": "REFUSE",
        "blockers_json": json.dumps(["trend expansion"]), "warnings_json": "[]",
        "decision_json": json.dumps({"headline": "STAND DOWN", "factors": [{"code": "FLOW", "score": 40}]}),
        "candidate_json": json.dumps({"strategy": "IRON_CONDOR", "tradeable": True, "net_credit": 2.4}),
        "counterfactual_metrics_json": json.dumps({"breached": True}),
    }
    item = serialize_decision(row)
    assert item["headline"] == "STAND DOWN"
    assert item["blockers"] == ["trend expansion"]
    assert item["candidate"]["credit"] == 2.4
    assert item["counterfactual_metrics"]["breached"] is True


def test_command_center_is_advisory_and_exposes_governance():
    payload = build_command_center(
        snapshot={"eligibility": {"decision": "REFUSE"}}, decisions=[],
        scorecard={"total": 0}, replay={"pending": 0},
        active_policy={"source": "DEFAULT_GOVERNED_POLICY", "source_run_id": None},
        calibration_runs=[],
    )
    assert payload["advisory_only"] is True
    assert payload["execution_authority"] is False
    assert payload["calibration_readiness"] == "NO_HISTORY"


def test_command_center_routes(tmp_path):
    app = Flask(__name__, template_folder="../templates")
    register_premium_discipline_routes(app, last_result_provider=lambda: {}, db_path=str(tmp_path / "cc.db"))
    client = app.test_client()
    assert client.get("/apex_os/premium_discipline").status_code == 200
    body = client.get("/api/premium_discipline/command-center").get_json()
    assert body["ok"] is True
    assert body["command_center"]["execution_authority"] is False
    assert "active_policy" in body["command_center"]
