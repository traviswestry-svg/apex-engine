import json
from engine import decision_provenance as P


def test_snapshot_is_deterministic_and_detects_replay_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setattr(P, "_READY", False)
    assert P.init_db()
    kwargs = dict(sample_id="s1", decision_time="2026-07-17T10:00:00", ticker="SPX",
                  raw_inputs={"b": 2, "a": 1}, normalized_inputs={"price": 6200},
                  quality_assessments={"chain": {"score": 90}},
                  feature_vector={"features": {"x": 1}})
    a = P.build_snapshot(**kwargs)
    b = P.build_snapshot(**kwargs)
    assert a["payload_hash"] == b["payload_hash"]
    assert P.write_snapshot(a)
    assert not P.write_snapshot(a)
    row = P.get_snapshot("s1")
    assert row["integrity_ok"] is True
    assert P.verify_replay("s1", a["payload"])["match"] is True
    changed = json.loads(json.dumps(a["payload"]))
    changed["normalized_inputs"]["price"] = 6201
    assert P.verify_replay("s1", changed)["match"] is False
