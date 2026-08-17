from pathlib import Path

import engine.silent_degradation_observability as sdo


def test_records_and_deduplicates(tmp_path, monkeypatch):
    db = tmp_path / "degradations.db"
    monkeypatch.setattr(sdo, "DEFAULT_DB", str(db))
    sdo._MEMORY.clear()
    for _ in range(2):
        sdo.record_degradation(
            component="canonical_market_state",
            operation="build",
            exc=RuntimeError("boom"),
            fallback="EMPTY_CANONICAL_MARKET_STATE",
            decision_authority_suppressed=True,
            source="test",
        )
    snap = sdo.snapshot()
    assert snap["event_groups"] == 1
    assert snap["occurrences"] == 2
    assert snap["decision_authority_suppressed_occurrences"] == 2
    assert snap["events"][0]["occurrence_count"] == 2


def test_memory_fallback_when_database_unavailable(monkeypatch):
    sdo._MEMORY.clear()
    def broken(*args, **kwargs):
        raise OSError("db unavailable")
    monkeypatch.setattr(sdo, "_connect", broken)
    result = sdo.record_degradation(
        component="scanner",
        operation="collect",
        exc=ValueError("bad"),
        fallback="CONTINUE",
    )
    assert result["recorded"] is False
    snap = sdo.snapshot()
    assert snap["source"] == "MEMORY_FALLBACK"
    assert snap["event_groups"] == 1


def test_observability_has_no_execution_authority(tmp_path, monkeypatch):
    db = tmp_path / "d.db"
    monkeypatch.setattr(sdo, "DEFAULT_DB", str(db))
    sdo._MEMORY.clear()
    sdo.record_degradation(
        component="trade_director",
        operation="provider",
        exc=RuntimeError("x"),
        fallback="FAIL_CLOSED",
        decision_authority_suppressed=True,
    )
    snap = sdo.snapshot()
    assert snap["execution_authority"] == "NONE"
