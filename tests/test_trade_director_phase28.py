import os
import tempfile


def _module(tmpdir):
    os.environ["APEX_LINEAGE_DB"] = os.path.join(tmpdir, "lineage.db")
    import engine.trade_director_data_lineage as lineage
    return lineage


def test_phase28_records_and_verifies_append_only_lineage():
    with tempfile.TemporaryDirectory() as tmp:
        lineage = _module(tmp)
        ctx = {
            "position": {"trade_id": "T-28", "symbol": "SPX"},
            "session_intelligence": {"version": "PHASE_11", "confidence": 81, "state": "RTH"},
            "decision_intelligence": {"version": "PHASE_19", "confidence": 88, "decision": "CALL"},
            "institutional_decision_engine": {"version": "PHASE_20", "state": "AUTHORIZED"},
        }
        result = lineage.build_data_lineage(ctx, persist=True)
        assert result["version"] == "PHASE_28"
        assert result["events_recorded_this_run"] == 3
        assert result["integrity"]["status"] == "VERIFIED"
        assert result["controls"]["broker_access"] is False
        history = lineage.lineage_history(20, "T-28")
        assert len(history) == 3
        tree = lineage.lineage_tree("T-28")
        assert tree["node_count"] == 3
        assert tree["edge_count"] >= 2


def test_phase28_deduplicates_identical_events_and_exports():
    with tempfile.TemporaryDirectory() as tmp:
        lineage = _module(tmp)
        payload = {"version": "PHASE_19", "decision": "PUT", "confidence": 77}
        first = lineage.record_lineage_event(payload, event_type="ENGINE_OUTPUT", entity_id="T2:19", trade_id="T2", phase="19")
        second = lineage.record_lineage_event(payload, event_type="ENGINE_OUTPUT", entity_id="T2:19", trade_id="T2", phase="19")
        assert first["lineage_id"] == second["lineage_id"]
        exported = lineage.export_lineage("T2")
        assert exported["event_count"] == 1
        assert exported["integrity"]["status"] == "VERIFIED"


def test_phase28_payload_hash_detects_tampering():
    with tempfile.TemporaryDirectory() as tmp:
        lineage = _module(tmp)
        event = lineage.record_lineage_event({"value": 1}, event_type="TEST", entity_id="tamper")
        import sqlite3
        conn = sqlite3.connect(lineage.lineage_db_path())
        conn.execute("DROP TRIGGER apex_lineage_events_no_update")
        conn.execute("UPDATE apex_lineage_events SET payload_json=? WHERE lineage_id=?", ('{"value":2}', event["lineage_id"]))
        conn.commit(); conn.close()
        check = lineage.verify_integrity("TEST")
        assert check["status"] == "TAMPER_DETECTED"
        assert check["critical_count"] >= 1
