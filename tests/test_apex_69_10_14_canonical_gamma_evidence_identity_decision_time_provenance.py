import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _gamma(net_gex=100.0, *, source_snapshot_at="2026-09-18T13:30:00+00:00", signed_terms=False):
    expirations = []
    if signed_terms:
        expirations = [
            {"dte": 0, "net_gamma_ratio": 0.25},
            {"dte": 1, "net_gamma_ratio": -0.10},
        ]
    return {
        "net_gex": net_gex,
        "net_gamma_ratio": 0.25,
        "gex_score": 62.0,
        "zero_gamma": 6000.0,
        "gex_status": "POSITIVE",
        "gamma_path": {
            "available": True,
            "spot": 6000.0,
            "path_version": "gamma_path.v2",
            "level_version": "levels.v1",
            "source_snapshot_at": source_snapshot_at,
            "current_regime": "POSITIVE_GAMMA",
        },
        "gamma_term_structure": {
            "available": True,
            "immediate": {"dte": 0, "net_gamma_ratio": 0.25},
            "maturity_concentration": {
                "zero_dte_gamma_share": 0.40,
                "zero_one_dte_gamma_share": 0.65,
                "seven_dte_gamma_share": 0.92,
                "structure_durability": "HIGH",
            },
            "expirations": expirations,
            "term_alignment": True if signed_terms else None,
            "term_divergence": False if signed_terms else None,
        },
    }


def test_release_identity_and_capability_registry_are_691014():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.14"
    assert manifest["build_name"] == "Canonical Gamma Evidence Identity & Decision-Time Provenance"
    assert manifest["database_schema_version"] == "6"
    g = manifest["guardrails"]
    assert g["canonical_gamma_snapshot_identity"] is True
    assert g["gamma_latest_state_substitution_for_historical_decisions"] is False
    assert g["gamma_provenance_changes_execution_authority"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.10.14" in registry
    assert "canonical_gamma_evidence_identity_decision_time_provenance:" in registry


def test_canonical_gamma_identity_is_deterministic_and_material_change_sensitive():
    from engine.gamma_transition import canonical_gamma_snapshot_id, snapshot_from_gamma

    a = snapshot_from_gamma(_gamma(100.30000000000001), observed_at="2026-09-18T13:30:05Z", received_at="2026-09-18T13:30:06Z")
    b = snapshot_from_gamma(_gamma(100.3), observed_at="2026-09-18T13:30:05Z", received_at="2026-09-18T13:30:07Z")
    # Receive time, JSON order, and binary float noise do not change one observation's identity.
    assert a["canonical_gamma_snapshot_id"] == b["canonical_gamma_snapshot_id"]
    assert canonical_gamma_snapshot_id(dict(reversed(list(a.items())))) == a["canonical_gamma_snapshot_id"]
    # Without provider observation identity/time, a distinct poll is honestly a distinct observation.
    later_poll = snapshot_from_gamma(_gamma(100.3), observed_at="2026-09-18T13:31:05Z")
    assert later_poll["canonical_gamma_snapshot_id"] != a["canonical_gamma_snapshot_id"]
    c = snapshot_from_gamma(_gamma(101.3), observed_at="2026-09-18T13:30:05Z")
    assert c["canonical_gamma_snapshot_id"] != a["canonical_gamma_snapshot_id"]


def test_gamma_dedup_and_provider_provenance_truth(tmp_path):
    from engine.gamma_transition import observe_gamma_transition

    db = tmp_path / "gamma.db"
    first = observe_gamma_transition(_gamma(), db_path=str(db), observed_at="2026-09-18T13:30:05Z", received_at="2026-09-18T13:30:06Z")
    second = observe_gamma_transition(_gamma(), db_path=str(db), observed_at="2026-09-18T13:30:05Z", received_at="2026-09-18T13:31:06Z")
    assert first["canonical_gamma_snapshot_id"] == second["canonical_gamma_snapshot_id"]
    assert first["snapshot_created"] is True and second["snapshot_deduplicated"] is True
    assert first["gamma_provider_source_timestamp"] is None
    assert first["gamma_source_timestamp_provenance"] == "APEX_DERIVED_PARSE_TIME"
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM gamma_observational_snapshots").fetchone()[0] == 1


def test_freshness_market_closed_and_term_regime_are_provider_gated():
    from engine.gamma_transition import freshness_for_snapshot, snapshot_from_gamma

    snap = snapshot_from_gamma(_gamma(), observed_at="2026-09-18T13:30:00Z")
    assert freshness_for_snapshot(snap, reference_at="2026-09-18T13:30:30Z")["freshness_state"] == "FRESH"
    assert freshness_for_snapshot(snap, reference_at="2026-09-18T13:33:00Z")["freshness_state"] == "AGING"
    stale = freshness_for_snapshot(snap, reference_at="2026-09-18T13:36:00Z", market_state="CLOSED")
    assert stale["freshness_state"] == "STALE"
    assert stale["session_context_state"] == "PRIOR_SESSION_CONTEXT"
    future = freshness_for_snapshot(snap, reference_at="2026-09-18T13:29:59Z")
    assert future["freshness_state"] == "UNKNOWN" and future["temporal_order_valid"] is False
    assert snap["term_regime_divergence_available"] is False
    signed = snapshot_from_gamma(_gamma(signed_terms=True), observed_at="2026-09-18T13:30:00Z")
    assert signed["term_regime_divergence_available"] is True


def test_continuity_gap_recovery_and_out_of_order_do_not_corrupt_current_authority(tmp_path):
    from engine.gamma_transition import observe_gamma_transition, current_gamma_integrity

    db = tmp_path / "gamma.db"
    a = observe_gamma_transition(_gamma(100), db_path=str(db), observed_at="2026-09-18T13:30:00Z")
    b = observe_gamma_transition(_gamma(110), db_path=str(db), observed_at="2026-09-18T13:31:00Z")
    c = observe_gamma_transition(_gamma(120), db_path=str(db), observed_at="2026-09-18T13:36:00Z")
    d = observe_gamma_transition(_gamma(130), db_path=str(db), observed_at="2026-09-18T13:37:00Z")
    oo = observe_gamma_transition(_gamma(140), db_path=str(db), observed_at="2026-09-18T13:35:00Z")
    assert a["continuity_state"] == "UNKNOWN"
    assert b["continuity_state"] == "CONTINUOUS"
    assert c["continuity_state"] == "GAPPED"
    assert d["continuity_state"] == "RECOVERED"
    assert oo["sequence_state"] == "OUT_OF_ORDER" and oo["is_current_authority"] is False
    current = current_gamma_integrity(ticker="SPX", db_path=str(db), reference_at="2026-09-18T13:37:10Z")
    assert current["canonical_gamma_snapshot_id"] == d["canonical_gamma_snapshot_id"]
    closed = current_gamma_integrity(ticker="SPX", db_path=str(db), reference_at="2026-09-19T13:37:10Z", market_state="CLOSED")
    assert closed["gamma_evidence_health"] == "PRIOR_SESSION_CONTEXT"


def test_current_gamma_integrity_ignores_replayed_rows_marked_current(tmp_path):
    from engine.gamma_transition import current_gamma_integrity, init_db, observe_gamma_transition

    db = tmp_path / "gamma.db"
    live = observe_gamma_transition(_gamma(100), db_path=str(db), observed_at="2026-09-18T13:30:00Z")
    assert init_db(str(db)) is True
    with sqlite3.connect(db) as c:
        c.execute(
            """INSERT INTO gamma_observational_snapshots(
                ticker,observed_at,source,snapshot_json,canonical_gamma_snapshot_id,received_at,persisted_at,
                provenance_class,replay_backfill_status,is_current_authority,freshness_state,continuity_state,
                sequence_state,session_context_state
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "SPX", "2026-09-18T13:40:00Z", "QUANTDATA_EXPOSURE_BY_STRIKE", "{}",
                "g_replayed_current", "2026-09-18T13:40:01Z", "2026-09-18T13:40:01Z",
                "REPLAYED", "BACKFILL", 1, "FRESH", "BACKFILLED", "HISTORICAL_INSERT", "REGULAR_SESSION",
            ),
        )
        c.commit()
    current = current_gamma_integrity(ticker="SPX", db_path=str(db), reference_at="2026-09-18T13:30:30Z")
    assert current["canonical_gamma_snapshot_id"] == live["canonical_gamma_snapshot_id"]
    assert current["provenance_class"] == "LIVE_OBSERVED"


def test_decision_time_captured_snapshots_remain_current_authority(tmp_path):
    from engine.gamma_transition import current_gamma_integrity, observe_gamma_transition

    db = tmp_path / "gamma.db"
    observe_gamma_transition(_gamma(100), db_path=str(db), observed_at="2026-09-18T13:30:00Z")
    captured = observe_gamma_transition(
        _gamma(105),
        db_path=str(db),
        observed_at="2026-09-18T13:31:00Z",
        provenance_class="DECISION_TIME_CAPTURED",
        replay_backfill_status="DECISION_TIME_CAPTURED",
    )
    assert captured["is_current_authority"] is True
    current = current_gamma_integrity(ticker="SPX", db_path=str(db), reference_at="2026-09-18T13:31:10Z")
    assert current["canonical_gamma_snapshot_id"] == captured["canonical_gamma_snapshot_id"]
    assert current["provenance_class"] == "DECISION_TIME_CAPTURED"


def test_decision_freezes_exact_gamma_and_later_update_cannot_mutate_it(tmp_path, monkeypatch):
    from engine.gamma_transition import observe_gamma_transition
    from engine.historical_evidence_lifecycle import capture_decision

    gamma_db = tmp_path / "gamma.db"
    evidence_db = tmp_path / "evidence.db"
    monkeypatch.setenv("DB_PATH", str(gamma_db))
    gt = observe_gamma_transition(_gamma(100), db_path=str(gamma_db), observed_at="2026-09-18T13:30:00Z", received_at="2026-09-18T13:30:05Z")
    gamma_payload = _gamma(100)
    gamma_payload["gamma_path"]["spot"] = 6000.0
    result = {
        "timestamp": "2026-09-18T13:30:10Z", "ticker": "SPX", "session": "OPEN",
        "market_state": {"price": 6000.0},
        "structured": {"expected_move": {"one_sigma": 40.0}},
        "gamma_path": gamma_payload["gamma_path"],
        "gamma_term_structure": gamma_payload["gamma_term_structure"],
        "gamma_transition": gt,
        "institutional_decision_object": {
            "decision_id": "decision-gamma-1", "timestamp": "2026-09-18T13:30:10Z", "ticker": "SPX",
            "action": "ENTER", "direction": "BULLISH", "actionable": True, "entry_reference": 6000.0,
            "conviction": {"score": 70}, "institutional_thesis": {"dominant_direction": "BULLISH"},
        },
    }
    out = capture_decision(result, session_state="OPEN", path=evidence_db)
    assert out["ok"] is True
    sid = gt["canonical_gamma_snapshot_id"]
    assert out["canonical_gamma_snapshot_id"] == sid
    assert out["snapshot"]["gamma_evidence"]["gamma_snapshot_age_seconds"] == 10.0
    assert out["snapshot"]["gamma_evidence"]["capacity_state"] == "STRONG"
    assert out["snapshot"]["gamma_evidence"]["capacity_ratio"] == 37.5
    assert out["snapshot"]["gamma_evidence"]["gamma_context_snapshot_id"] == sid
    observe_gamma_transition(_gamma(200), db_path=str(gamma_db), observed_at="2026-09-18T13:31:00Z")
    with sqlite3.connect(evidence_db) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM decisions WHERE decision_id=?", (out["decision_id"],)).fetchone()
        stored = json.loads(row["snapshot_json"])
    assert row["canonical_gamma_snapshot_id"] == sid
    assert stored["gamma_evidence"]["canonical_gamma_snapshot_id"] == sid
    assert stored["gamma_evidence"]["later_gamma_substitution_allowed"] is False


def test_trigger_and_grader_preserve_frozen_gamma_linkage(tmp_path):
    from engine.evidence_pipeline import record_price, record_snapshot
    from engine.outcome_grader import run_grader
    from engine.trigger_observatory import record_canonical_snapshot

    evidence_db = tmp_path / "evidence.db"
    trigger_db = tmp_path / "triggers.db"
    now = datetime.now(timezone.utc)
    observed = (now - timedelta(seconds=20)).isoformat()
    sid = "g_frozen_123"
    snapshot = {
        "decision_id": "d1", "timestamp": observed, "ticker": "SPX", "session": "OPEN",
        "direction": "BULLISH", "action": "ENTER", "entry_reference": 6000.0, "confidence": 70.0,
        "learning_eligible": True, "execution_actionable": True,
        "canonical_gamma_snapshot_id": sid, "gamma_snapshot_age_seconds": 12.0,
        "gamma_provenance_class": "LIVE_OBSERVED",
        "gamma_evidence": {"linkage_status": "LINKED", "canonical_gamma_snapshot_id": sid,
                           "freshness_state": "FRESH", "continuity_state": "CONTINUOUS",
                           "provenance_class": "LIVE_OBSERVED", "gamma_snapshot_age_seconds": 12.0,
                           "gamma_regime": "POSITIVE_GAMMA", "decision_time_frozen": True},
    }
    assert record_snapshot(snapshot, path=evidence_db) is True
    record_price("SPX", 6002.0, observed_at=(now - timedelta(seconds=17)).isoformat(), path=evidence_db)
    grade = run_grader(path=evidence_db, horizon_seconds=5)
    assert grade["graded"] == 1
    with sqlite3.connect(evidence_db) as c:
        outcome = json.loads(c.execute("SELECT outcome_json FROM grading_results WHERE decision_id='d1'").fetchone()[0])
    assert outcome["gamma_evidence"]["canonical_gamma_snapshot_id"] == sid
    assert outcome["gamma_evidence"]["latest_gamma_lookup_performed"] is False

    canonical = {
        "timestamp": observed, "ticker": "SPX", "market_state": {"price": 6000.0},
        "historical_evidence_capture": {"decision_id": "d1", "canonical_gamma_snapshot_id": sid},
        "institutional_decision_object": {"action": "ENTER", "direction": "BULLISH", "actionable": True},
    }
    record_canonical_snapshot(canonical, canonical_decision_id="d1", path=str(trigger_db))
    with sqlite3.connect(trigger_db) as c:
        assert c.execute("SELECT canonical_gamma_snapshot_id FROM observed_trade_triggers WHERE decision_id='d1'").fetchone()[0] == sid


def test_trigger_fallback_reads_frozen_gamma_evidence_linkage(tmp_path):
    from engine.trigger_observatory import record_canonical_snapshot

    trigger_db = tmp_path / "triggers.db"
    sid = "g_frozen_only"
    canonical = {
        "timestamp": "2026-09-18T13:30:00Z",
        "ticker": "SPX",
        "market_state": {"price": 6000.0},
        "institutional_decision_object": {"decision_id": "d-frozen", "action": "ENTER", "direction": "BULLISH", "actionable": True},
        "gamma_evidence": {"canonical_gamma_snapshot_id": sid},
        "gamma_regime": "POSITIVE_GAMMA",
    }
    record_canonical_snapshot(canonical, path=str(trigger_db))
    with sqlite3.connect(trigger_db) as c:
        assert c.execute("SELECT canonical_gamma_snapshot_id FROM observed_trade_triggers WHERE decision_id='d-frozen'").fetchone()[0] == sid



def test_malformed_timestamps_fail_closed_and_future_receipt_is_not_decision_time_evidence(tmp_path):
    from engine.gamma_transition import observe_gamma_transition, decision_time_gamma_evidence

    db = tmp_path / "gamma.db"
    bad = observe_gamma_transition(_gamma(), db_path=str(db), observed_at="not-a-time")
    assert bad["status"] == "UNAVAILABLE" and bad["freshness_state"] == "UNKNOWN"
    good = observe_gamma_transition(_gamma(), db_path=str(db), observed_at="2026-09-18T13:30:00Z", received_at="2026-09-18T13:30:10Z")
    frozen = decision_time_gamma_evidence(good["canonical_gamma_snapshot_id"], decision_time="2026-09-18T13:30:05Z", db_path=str(db))
    assert frozen["available_at_decision"] is False
    assert frozen["freshness_state"] == "UNKNOWN"
    assert frozen["temporal_order_valid"] is False


def test_insert_failure_is_not_reported_as_deduplicated(monkeypatch, tmp_path):
    import engine.gamma_transition as gt

    class _BrokenConnection:
        row_factory = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("forced write failure")

    monkeypatch.setattr(gt, "init_db", lambda path=None: True)
    monkeypatch.setattr(gt, "connect", lambda *args, **kwargs: _BrokenConnection())
    monkeypatch.setattr(gt, "compute_transition", lambda *args, **kwargs: {"transition_state": "UNCHANGED"})
    monkeypatch.setattr(
        gt,
        "_continuity_for_new",
        lambda *args, **kwargs: {
            "continuity_state": "UNKNOWN",
            "sequence_state": "FIRST_OBSERVATION",
            "is_current_authority": True,
            "gap_seconds": None,
        },
    )
    out = gt.observe_gamma_transition(_gamma(), db_path=str(tmp_path / "gamma.db"), observed_at="2026-09-18T13:30:00Z")
    assert out["status"] == "UNAVAILABLE"
    assert out["snapshot_created"] is False
    assert out["snapshot_deduplicated"] is False
    assert out["evidence_integrity_available"] is False

def test_legacy_schema_migrations_are_idempotent_and_preserve_rows(tmp_path):
    from engine.gamma_transition import init_db
    from engine.evidence_pipeline import _connect
    from engine.trigger_observatory import initialize_store

    gamma_db = tmp_path / "legacy_gamma.db"
    with sqlite3.connect(gamma_db) as c:
        c.execute("""CREATE TABLE gamma_observational_snapshots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,ticker TEXT NOT NULL,observed_at TEXT NOT NULL,
            source_timestamp TEXT,source TEXT,path_version TEXT,net_gex REAL,gamma_flip REAL,
            zero_dte_share REAL,zero_one_dte_share REAL,weekly_gamma_share REAL,durability TEXT,
            capacity_ratio REAL,snapshot_json TEXT NOT NULL)""")
        c.execute("INSERT INTO gamma_observational_snapshots(ticker,observed_at,snapshot_json) VALUES('SPX','2026-09-01T13:30:00Z','{}')")
    assert init_db(str(gamma_db)) is True and init_db(str(gamma_db)) is True
    with sqlite3.connect(gamma_db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(gamma_observational_snapshots)")}
        assert "canonical_gamma_snapshot_id" in cols
        assert c.execute("SELECT canonical_gamma_snapshot_id FROM gamma_observational_snapshots").fetchone()[0] is None

    evidence_db = tmp_path / "legacy_evidence.db"
    with sqlite3.connect(evidence_db) as c:
        c.executescript("""CREATE TABLE decisions(decision_id TEXT PRIMARY KEY,observed_at TEXT NOT NULL,ticker TEXT NOT NULL,session TEXT,direction TEXT,action TEXT,entry_price REAL,confidence REAL,learning_eligible INTEGER NOT NULL,snapshot_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING');
        CREATE TABLE price_samples(id INTEGER PRIMARY KEY AUTOINCREMENT,ticker TEXT NOT NULL,observed_at TEXT NOT NULL,price REAL NOT NULL);
        CREATE TABLE grading_results(id INTEGER PRIMARY KEY AUTOINCREMENT,decision_id TEXT NOT NULL UNIQUE,graded_at TEXT NOT NULL,status TEXT NOT NULL,exclusion_reason TEXT,horizon_seconds INTEGER,outcome_json TEXT NOT NULL);""")
        c.execute("INSERT INTO decisions VALUES('legacy','2026-09-01T13:30:00Z','SPX','OPEN','BULLISH','ENTER',6000,60,1,'{}','PENDING')")
    with _connect(evidence_db) as c:
        row = c.execute("SELECT canonical_gamma_snapshot_id FROM decisions WHERE decision_id='legacy'").fetchone()
        assert row[0] is None

    trigger_db = tmp_path / "legacy_trigger.db"
    # The canonical initializer is itself the migration contract; repeated execution must be safe.
    assert initialize_store(str(trigger_db), reconcile=False)["ok"] is True
    assert initialize_store(str(trigger_db), reconcile=False)["ok"] is True
    with sqlite3.connect(trigger_db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(observed_trade_triggers)")}
        assert "canonical_gamma_snapshot_id" in cols


def test_existing_dealer_eligibility_gate_handles_integrity_without_parallel_engine():
    from engine.evidence_eligibility import evaluate_evidence_eligibility

    opinion = {"direction": "BULLISH", "freshness_state": "CURRENT"}
    base = {"gamma_context": {"structure_durability": "HIGH", "capacity_state": "STRONG"}}
    legacy = evaluate_evidence_eligibility("dealer", opinion, base)
    assert legacy["state"] == "FULL"
    aging = evaluate_evidence_eligibility("dealer", opinion, {**base, "gamma_transition": {
        "canonical_gamma_snapshot_id": "g1", "evidence_integrity_available": True,
        "freshness_state": "AGING", "continuity_state": "CONTINUOUS", "provenance_class": "LIVE_OBSERVED"}})
    assert aging["state"] == "DISCOUNTED" and "AGING_CANONICAL_GAMMA_EVIDENCE" in aging["reasons"]
    stale = evaluate_evidence_eligibility("dealer", opinion, {**base, "gamma_transition": {
        "canonical_gamma_snapshot_id": "g2", "evidence_integrity_available": True,
        "freshness_state": "STALE", "continuity_state": "CONTINUOUS", "provenance_class": "LIVE_OBSERVED"}})
    assert stale["state"] == "CONTEXT_ONLY"
    unknown = evaluate_evidence_eligibility("dealer", opinion, {**base, "gamma_transition": {
        "canonical_gamma_snapshot_id": "g3", "evidence_integrity_available": True,
        "freshness_state": "UNKNOWN", "continuity_state": "UNKNOWN", "provenance_class": "UNKNOWN"}})
    assert unknown["state"] == "INELIGIBLE"


def test_storage_projection_keeps_bounded_gamma_reference_under_hard_guard(monkeypatch):
    import engine.evidence_pipeline as ep

    monkeypatch.setattr(ep, "MAX_PERSISTED_SNAPSHOT_BYTES", 512)
    sid = "g_storage_123"
    projected = ep._persisted_snapshot_projection({
        "decision_id": "d-storage", "timestamp": "2026-09-18T13:30:00Z", "ticker": "SPX",
        "canonical_gamma_snapshot_id": sid, "gamma_snapshot_age_seconds": 8.0,
        "gamma_provenance_class": "LIVE_OBSERVED",
        "gamma_evidence": {"canonical_gamma_snapshot_id": sid, "freshness_state": "FRESH"},
        "runtime_bulk": "x" * 10000,
    })
    assert projected["canonical_gamma_snapshot_id"] == sid
    assert projected["gamma_evidence"]["canonical_gamma_snapshot_id"] == sid
    assert projected["storage_projection"]["hard_size_guardrail_applied"] is True

def test_gamma_freshness_thresholds_are_registered_configuration_variables():
    from engine import configuration_governance as cg

    expected = {
        "APEX_GAMMA_FRESH_SECONDS": "120",
        "APEX_GAMMA_AGING_SECONDS": "300",
        "APEX_GAMMA_EXPECTED_CADENCE_SECONDS": "60",
        "APEX_GAMMA_GAP_SECONDS": "180",
        "APEX_GAMMA_QUANTDATA_EXPOSURE_BY_STRIKE_FRESH_SECONDS": "120",
        "APEX_GAMMA_QUANTDATA_EXPOSURE_BY_STRIKE_AGING_SECONDS": "300",
        "APEX_GAMMA_QUANTDATA_EXPOSURE_BY_STRIKE_EXPECTED_CADENCE_SECONDS": "60",
        "APEX_GAMMA_QUANTDATA_EXPOSURE_BY_STRIKE_GAP_SECONDS": "180",
    }
    for name, default in expected.items():
        assert name in cg.REGISTRY
        assert cg.REGISTRY[name].default == default
        assert cg.REGISTRY[name].used_in_code is True

    env = {name: default for name, default in expected.items()}
    issues = cg.diagnostics(env)["issues"]
    assert not [issue for issue in issues if issue.get("code") == "UNKNOWN_APEX_VARIABLE" and issue.get("variable") in expected]
