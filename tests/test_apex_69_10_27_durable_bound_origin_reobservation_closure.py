import json
from pathlib import Path
import pytest
from engine import flow_pl_store, feature_store_db
from engine.flow_pl_pipeline import reobserve_bound_feature_origins

@pytest.fixture()
def stores(monkeypatch, tmp_path):
    db = tmp_path / "apex_69_10_27.db"
    monkeypatch.setattr(flow_pl_store, "_DB_PATH", str(db))
    monkeypatch.setattr(feature_store_db, "_DB_PATH", str(db))
    monkeypatch.setattr(flow_pl_store, "_DB_READY", False)
    monkeypatch.setattr(feature_store_db, "_DB_READY", False)
    assert feature_store_db.init_db(); assert flow_pl_store.init_db()
    return db

def _seed():
    session="2026-10-01"; sid="s_origin"; key="SPX|CALL|2026-10-02|UNCERTAIN"; dt=f"{session}T10:00:00"
    pl={"event_id":"stable-event","markable":True,"estimated_pl_dollars":0.0,
        "ticker":"SPX","contract_type":"CALL","strike":7000.0,"expiration":"2026-10-02",
        "position_side":"LONG","contracts":1,"multiplier":100.0,"entry_time_et":"09:59:58",
        "entry_mark":10.0,"current_mark":10.0,"mark_methodology":"CONSERVATIVE"}
    assert flow_pl_store.record_observation(pl, cluster_key=key, session_date=session, spot=7000.0, iv=.2)
    assert flow_pl_store.register_sample_identity(sample_id=sid,session_date=session,
        legacy_cluster_key=key,decision_time=dt,origin_event_ids=["stable-event"])
    flow_pl_store.record_sample_pl_lifecycle(sample_id=sid,session_date=session,
        legacy_cluster_key=key,decision_time=dt,state="AWAITING_REAL_PL",reason="TEST")
    return session,sid,key,dt

def test_release_truth():
    m=json.loads(Path("config/apex_release_manifest.json").read_text())
    assert m["apex_version"] == "69.10.35"
    assert m["build_name"] == "Canonical Settlement Cohort Identity Alignment"
    assert m["guardrails"]["durable_bound_origin_reobservation"] is True
    assert m["guardrails"]["origin_reobservation_requires_exact_registered_owner"] is True

def test_bound_origin_reprices_without_current_tape_membership(stores):
    session,sid,key,dt=_seed()
    def chain(symbol, expiration, side):
        return [{"ticker":"SPX","expiration":expiration,"optionType":"CALL","strike":7000,
                 "bid":12.0,"ask":12.5,"iv":.21,"quote_age_seconds":1,"source":"test"}]
    r=reobserve_bound_feature_origins(session_date_value=session,chain_fetcher=chain,
                                      last_result_provider=lambda:{"market_state":{"price":7010}})
    assert r["candidates"] == 1 and r["samples_seen"] == 1 and r["samples_marked"] == 1
    assert r["excursions_inserted"] == 1 and r["owner_validation_failed"] == 0
    exc=flow_pl_store.get_sample_excursions([sid])[sid]
    assert exc["mfe_dollars"] == 200.0

def test_unregistered_or_unbound_events_cannot_gain_authority(stores):
    session,sid,key,dt=_seed()
    with flow_pl_store._conn() as c:
        c.execute("DELETE FROM flow_sample_identity_map WHERE sample_id=?",(sid,)); c.commit()
    def chain(symbol, expiration, side):
        return [{"ticker":"SPX","expiration":expiration,"optionType":"CALL","strike":7000,
                 "bid":12.0,"ask":12.5,"iv":.21,"quote_age_seconds":1,"source":"test"}]
    r=reobserve_bound_feature_origins(session_date_value=session,chain_fetcher=chain)
    assert r["owner_validation_failed"] == 1 and r["samples_marked"] == 0
    assert flow_pl_store.get_sample_excursions([sid]) == {}

def test_missing_live_quote_fails_closed(stores):
    session,sid,key,dt=_seed()
    r=reobserve_bound_feature_origins(session_date_value=session,chain_fetcher=lambda *a: [])
    assert r["unmarkable"] == 1 and r["samples_marked"] == 0
    assert flow_pl_store.get_sample_excursions([sid]) == {}
