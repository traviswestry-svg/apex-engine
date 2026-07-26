from engine.evidence_pipeline_trace import build_trace
from engine.release_manifest import manifest


def test_trace_is_read_only_and_has_ordered_stages(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("APEX_EVIDENCE_PIPELINE_DB", str(tmp_path / "evidence.db"))
    trace = build_trace()
    assert trace["ok"] is True
    assert trace["guardrails"]["read_only"] is True
    assert [s["name"] for s in trace["stages"]] == [
        "recommendation_created", "decision_snapshot_stored", "feature_vector_stored",
        "outcome_eligible", "outcome_graded", "adaptive_learning", "confidence_updated",
    ]


def test_manifest_uses_canonical_release_authority():
    # Was a literal '47.0.6' pin — such pins break on every release and rot
    # silently. The current-release literal lives in ONE place
    # (tests/test_apex_48_2_version.py); here we assert the manifest reports
    # whatever the release manager declares canonical.
    from engine.release_manager import APP_VERSION
    assert manifest()["apex_version"] == APP_VERSION
