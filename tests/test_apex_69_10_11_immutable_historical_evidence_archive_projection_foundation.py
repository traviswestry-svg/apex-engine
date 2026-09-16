import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _make_trigger_db(path: Path):
    from engine.trigger_observatory import initialize_store
    initialize_store(str(path), reconcile=False)
    evidence = {
        "decision": {"decision_id": "d1", "action": "NO_TRADE", "narrative": "x" * 10000},
        "entry_premium": 10.5,
        "pine": {"target1_premium": 12.0},
        "bulk": "y" * 20000,
    }
    with sqlite3.connect(path) as c:
        c.execute(
            """INSERT INTO observed_trade_triggers(
            trigger_id,source_event_key,source,trigger_type,setup_family,symbol,direction,disposition,
            triggered_at,observed_at,blocker_codes_json,evidence_json,etrade_handoff_json,status,
            observation_count,observation_window_seconds,execution_authority,broker_mutation,
            production_effect,decision_id,canonical_grade_status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "t1", "e1", "TEST", "ENTER", "TEST", "SPX", "BULLISH", "OBSERVED",
                "2026-08-25T12:00:00+00:00", "2026-08-25T12:00:00+00:00", "[]",
                json.dumps(evidence, separators=(",", ":")), "{}", "OBSERVED", 1, 300, 0, 0,
                "OBSERVATIONAL_ONLY", "d1", "GRADED", "2026-08-25T12:00:00+00:00",
                "2026-08-25T12:00:00+00:00",
            ),
        )
        c.commit()
    return json.dumps(evidence, separators=(",", ":"))


def _make_evidence_db(path: Path):
    from engine.evidence_pipeline import _connect
    snap = {
        "decision_id": "d1", "timestamp": "2026-08-25T12:00:00+00:00", "ticker": "SPX",
        "action": "NO_TRADE", "direction": "NEUTRAL", "learning_eligible": False,
        "eligibility_reason": "TEST",
        "institutional_decision_object": {"action": "NO_TRADE", "narrative": "x" * 15000},
        "runtime_bulk": "z" * 20000,
    }
    raw = json.dumps(snap, separators=(",", ":"))
    with _connect(path) as c:
        c.execute(
            "INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,entry_price,confidence,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("d1", "2026-08-25T12:00:00+00:00", "SPX", "RTH", "NEUTRAL", "NO_TRADE", None, 50, 0, raw, "GRADED"),
        )
        c.commit()
    return raw


def _fetch_trigger_row(path: Path, trigger_id: str) -> dict:
    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT * FROM observed_trade_triggers WHERE trigger_id=?",
            (trigger_id,),
        ).fetchone()
    return dict(row)


def test_release_truth_and_archive_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.13"
    assert manifest["build_name"] == "Historical Payload Archive Pagination & Complete Shadow Validation Closure"
    g = manifest["guardrails"]
    assert g["historical_payload_archive_foundation"] is True
    assert g["historical_payload_archive_additive_only"] is True
    assert g["historical_payload_archive_immutable"] is True
    assert g["historical_payload_production_read_redirect_enabled"] is False
    assert g["historical_payload_mass_compaction_enabled"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.10.13" in registry
    assert "immutable_historical_evidence_archive_projection_foundation:" in registry


def test_archive_round_trip_is_exact_and_canonical_source_unchanged(tmp_path):
    from engine.historical_payload_archive import archive_one, retrieve_archived_payload
    source = tmp_path / "trigger.db"
    archive = tmp_path / "archive.db"
    raw = _make_trigger_db(source)
    before = _fetch_trigger_row(source, "t1")
    out = archive_one(payload_type="TRIGGER_EVIDENCE", row_id="t1", observed_at="2026-08-25T12:00:00+00:00", raw_payload=raw, path=archive, apply=True)
    assert out["ok"] is True and out["state"] == "ARCHIVED_VERIFIED"
    assert _fetch_trigger_row(source, "t1") == before
    restored = retrieve_archived_payload("TRIGGER_EVIDENCE", "t1", path=archive)
    assert restored["ok"] is True
    assert restored["payload"] == raw
    assert restored["source_sha256"] == out["source_sha256"]


def test_archive_identity_conflict_fails_closed_and_sql_archive_is_immutable(tmp_path):
    from engine.historical_payload_archive import archive_one
    archive = tmp_path / "archive.db"
    first = archive_one(payload_type="TRIGGER_EVIDENCE", row_id="t1", observed_at=None, raw_payload='{"a":1}', path=archive, apply=True)
    assert first["ok"] is True
    conflict = archive_one(payload_type="TRIGGER_EVIDENCE", row_id="t1", observed_at=None, raw_payload='{"a":2}', path=archive, apply=True)
    assert conflict["ok"] is False and conflict["state"] == "SOURCE_ID_HASH_CONFLICT"
    with sqlite3.connect(archive) as c:
        try:
            c.execute("UPDATE historical_payload_archive SET integrity_status='X' WHERE row_id='t1'")
            c.commit()
            assert False, "immutable archive update unexpectedly succeeded"
        except sqlite3.DatabaseError:
            pass
        try:
            c.execute("DELETE FROM historical_payload_archive WHERE row_id='t1'")
            c.commit()
            assert False, "immutable archive delete unexpectedly succeeded"
        except sqlite3.DatabaseError:
            pass


def test_archive_batch_dry_run_does_not_create_sidecar(tmp_path):
    from engine.historical_payload_archive import archive_batch
    source = tmp_path / "trigger.db"
    archive = tmp_path / "archive.db"
    _make_trigger_db(source)
    out = archive_batch(payload_type="TRIGGER_EVIDENCE", source_path=source, archive_path=archive, limit=10, apply=False)
    assert out["ok"] is True
    assert out["rows_archived"] == 0
    assert out["canonical_source_mutated"] is False
    assert not archive.exists()


def test_shadow_validation_requires_archive_then_passes_exact_round_trip(tmp_path):
    from engine.historical_payload_archive import archive_batch, shadow_validate
    source = tmp_path / "evidence.db"
    archive = tmp_path / "archive.db"
    _make_evidence_db(source)
    before = shadow_validate(payload_type="DECISION_SNAPSHOT", source_path=source, archive_path=archive, limit=10)
    assert before["shadow_read_ready"] is False
    assert before["archive_misses"] == 1
    written = archive_batch(payload_type="DECISION_SNAPSHOT", source_path=source, archive_path=archive, limit=10, apply=True)
    assert written["ok"] is True and written["rows_archived"] == 1
    after = shadow_validate(payload_type="DECISION_SNAPSHOT", source_path=source, archive_path=archive, limit=10)
    assert after["shadow_read_ready"] is True
    assert after["exact_archive_matches"] == 1
    assert after["production_reads_redirected"] is False


def test_compaction_readiness_ratchets_to_foundation_but_stays_fail_closed(tmp_path):
    from engine.historical_payload_compaction import audit_historical_payload_compaction
    t = tmp_path / "trigger.db"
    e = tmp_path / "evidence.db"
    _make_trigger_db(t)
    _make_evidence_db(e)
    out = audit_historical_payload_compaction(trigger_path=t, evidence_path=e, sample_limit=10)
    assert out["version"] == "69.10.11"
    assert out["compaction_readiness"]["ready_for_historical_rewrite"] is False
    assert out["compaction_readiness"]["state"] == "FOUNDATION_IMPLEMENTED_AWAITING_ARCHIVE_AND_SHADOW_VALIDATION"
    assert out["compaction_readiness"]["production_read_redirect_enabled"] is False
    assert out["archive_foundation"]["implemented"] is True


def test_operator_cli_exposes_archive_and_shadow_actions():
    text = (ROOT / "scripts/apex_storage_maintenance.py").read_text()
    for action in (
        "payload-archive-plan", "payload-archive-status", "archive-trigger-payloads",
        "archive-decision-payloads", "shadow-validate-trigger-payloads",
        "shadow-validate-decision-payloads",
    ):
        assert action in text
    assert "--limit" in text
    assert "--apply" in text


def test_critical_capacity_blocks_archive_apply(monkeypatch, tmp_path):
    import engine.historical_payload_archive as hpa
    source = tmp_path / "trigger.db"
    archive = tmp_path / "archive.db"
    _make_trigger_db(source)
    monkeypatch.setattr(hpa, "_archive_capacity_status", lambda path=archive: {
        "root": str(tmp_path), "free_pct": 10.0, "state": "CRITICAL",
        "archive_write_allowed": False, "critical_write_block": True,
    })
    out = hpa.archive_batch(payload_type="TRIGGER_EVIDENCE", source_path=source, archive_path=archive, limit=10, apply=True)
    assert out["ok"] is False
    assert out["state"] == "STORAGE_CRITICAL_ARCHIVE_WRITE_BLOCKED"
    assert out["rows_archived"] == 0
    assert not archive.exists()
