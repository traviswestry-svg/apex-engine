from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.evidence_pipeline import _persisted_snapshot_projection, record_snapshot
from engine.storage_retention import _decision_storage_amplification

ROOT = Path(__file__).resolve().parents[1]


def _large_snapshot(decision_id: str = "d1") -> dict:
    repeated = "X" * 350_000
    return {
        "decision_id": decision_id,
        "timestamp": "2026-08-26T15:00:00+00:00",
        "ticker": "SPX",
        "session": "RTH",
        "direction": "BULLISH",
        "action": "NO_TRADE",
        "entry_reference": 6500.0,
        "confidence": 72.0,
        "learning_eligible": True,
        "observational_learning_eligible": True,
        "observational_only": True,
        "eligibility_reason": "OBSERVATIONAL_DIRECTIONAL_THESIS",
        "setup": "TEST",
        "market_regime": "TREND",
        "gamma_regime": "POSITIVE",
        "volatility_regime": "NORMAL",
        "auction_regime": "BALANCED",
        "institutional_decision_object": {
            "ticker": "SPX", "strategy": "TEST", "action": "NO_TRADE", "direction": "BULLISH",
            "actionable": False, "decision_authority": "institutional_decision_object",
            "market_narrative": {"huge": repeated},
            "narrative": {"huge": repeated},
            "evidence_and_provenance": {"huge": repeated},
            "evidence_graph": {"huge": repeated},
            "provider_health": {"huge": repeated},
        },
    }


def test_release_is_69_4_4_three_part_and_manifest_truths_hold():
    m = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert m["apex_version"] == "69.4.4"
    assert m["semantic_version"] == "69.4.4"
    assert m["application_version"] == "69.4.4"
    g = m["guardrails"]
    assert g["decision_snapshot_storage_projection_bounded"] is True
    assert g["decision_snapshot_full_institutional_object_replicated"] is False
    assert g["decision_snapshot_projection_changes_trade_decisions"] is False
    assert g["decision_snapshot_projection_changes_execution_authority"] is False
    assert g["historical_decision_rows_rewritten_automatically"] is False


def test_projection_removes_redundant_ido_bulk_and_preserves_semantics_and_hash():
    source = _large_snapshot()
    source_bytes = len(json.dumps(source, default=str, separators=(",", ":"), sort_keys=True).encode())
    projected = _persisted_snapshot_projection(source)
    persisted_bytes = len(json.dumps(projected, default=str, separators=(",", ":"), sort_keys=True).encode())
    assert source_bytes > 1_000_000
    assert persisted_bytes < 20_000
    assert projected["direction"] == source["direction"]
    assert projected["action"] == source["action"]
    assert projected["learning_eligible"] is True
    assert projected["observational_only"] is True
    assert projected["setup"] == "TEST"
    ido = projected["institutional_decision_object"]
    assert ido["strategy"] == "TEST"
    assert "market_narrative" not in ido
    assert "narrative" not in ido
    assert "evidence_and_provenance" not in ido
    meta = projected["storage_projection"]
    assert meta["projection_version"] == "69.4.4"
    assert meta["source_snapshot_bytes"] == source_bytes
    assert len(meta["source_snapshot_sha256"]) == 64
    assert meta["canonical_decision_semantics_preserved"] is True


def test_record_snapshot_persists_projection_but_attribution_remains_available(tmp_path):
    db = tmp_path / "evidence.db"
    source = _large_snapshot("d2")
    assert record_snapshot(source, path=db) is True
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT snapshot_json FROM decisions WHERE decision_id='d2'").fetchone()
        snap = json.loads(row["snapshot_json"])
        assert len(row["snapshot_json"].encode()) < 20_000
        assert snap["storage_projection"]["projection_version"] == "69.4.4"
        # capture_context receives the full contemporaneous source and persists a separate compact attribution row.
        attr = c.execute("SELECT decision_id,action_class,direction FROM decision_effectiveness_attribution WHERE decision_id='d2'").fetchone()
        assert attr is not None
        assert attr["direction"] == "BULLISH"


def test_amplification_audit_returns_sizes_only_and_mutates_nothing(tmp_path):
    db = tmp_path / "audit.db"
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE decisions(decision_id TEXT PRIMARY KEY, observed_at TEXT, snapshot_json TEXT)")
    for i in range(3):
        snap = _large_snapshot(f"d{i}")
        c.execute("INSERT INTO decisions VALUES(?,?,?)", (f"d{i}", f"2026-08-26T15:0{i}:00+00:00", json.dumps(snap)))
    c.commit()
    before = c.total_changes
    out = _decision_storage_amplification(c)
    assert out["rows"] == 3
    assert out["snapshot_json_average_bytes"] > 1_000_000
    assert out["payload_values_exposed"] is False
    assert out["historical_rows_mutated"] is False
    assert out["largest_sample_top_level_bytes"][0]["key"] == "institutional_decision_object"
    assert c.total_changes == before
    assert c.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 3
    c.close()


def test_registry_accounts_for_69_4_4_without_new_authority():
    r = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert 'apex_version: 69.4.4' in r
    assert 'decision_evidence_storage_amplification_closure:' in r
    assert 'production_effect: STORAGE_SHAPE_ONLY' in r
    assert 'decision_authority: none' in r
    assert 'execution_authority: none' in r
    assert 'no_automatic_historical_rewrite' in r
