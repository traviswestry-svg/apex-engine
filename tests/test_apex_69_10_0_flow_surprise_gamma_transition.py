from __future__ import annotations

import datetime as dt
import json

from engine.flow_surprise import evaluate_flow_surprise, session_time_bucket
from engine import feature_store_db
from engine.gamma_transition import init_db, compute_transition
from engine.canonical_persistence import connect
from engine.dynamic_state import build_dynamic_state


def _history(n=20, *, bucket_time="2026-09-01T10:05:00", expiration="2026-09-01"):
    rows=[]
    for i in range(n):
        rows.append({"session_date":"2026-09-01", "decision_time":bucket_time,
                     "features":{"cluster_expiration":expiration,
                                 "cluster_total_premium":100000+i*1000,
                                 "cluster_total_contracts":100+i,
                                 "cluster_duration_seconds":50}})
    return rows


def test_flow_surprise_time_bucket_and_expiration_class_separation():
    h=_history(20)+_history(20, bucket_time="2026-09-01T10:35:00")+_history(20, expiration="2026-09-08")
    cl={"cluster_id":"canonical-1","expiration":"2026-09-01","total_premium":250000,"total_contracts":250,"duration_seconds":50}
    out=evaluate_flow_surprise(cl, session_date="2026-09-01", decision_time="2026-09-01T10:10:00", historical_rows=h)
    assert out["baseline_sample_size"] == 20
    assert out["baseline_context"]["session_time_bucket"] == session_time_bucket("2026-09-01T10:10:00")
    assert out["baseline_context"]["expiration_class"] == "0DTE"


def test_flow_surprise_ratios_percentiles_and_canonical_identity_are_observational():
    cl={"cluster_id":"canonical-xyz","expiration":"2026-09-01","total_premium":300000,"total_contracts":300,"duration_seconds":50}
    out=evaluate_flow_surprise(cl, session_date="2026-09-01", decision_time="2026-09-01T10:10:00", historical_rows=_history())
    assert out["status"] == "AVAILABLE"
    assert out["relative_premium_activity"] > 2
    assert out["premium_percentile"] == 100.0
    assert out["volume_percentile"] == 100.0
    assert out["identity_source"] == "canonical_flow_cluster_id"
    assert out["cluster_id"] == "canonical-xyz"
    assert out["behavioral_authority"] is False and out["execution_authority"] is False
    assert "independence_factor" not in out  # surprise never re-discounts canonical independence


def test_flow_surprise_insufficient_history_fails_closed():
    cl={"cluster_id":"c","expiration":"2026-09-01","total_premium":1,"total_contracts":1,"duration_seconds":1}
    out=evaluate_flow_surprise(cl, session_date="2026-09-01", decision_time="2026-09-01T10:10:00", historical_rows=_history(5))
    assert out["flow_surprise_state"] == "INSUFFICIENT_HISTORY"
    assert out["premium_percentile"] is None
    assert out["relative_premium_activity"] is None


def test_flow_surprise_context_is_immutable_first_write_wins(tmp_path, monkeypatch):
    db=tmp_path/"apex.db"; monkeypatch.setattr(feature_store_db, "_DB_PATH", str(db)); monkeypatch.setattr(feature_store_db, "_DB_READY", False)
    assert feature_store_db.init_db()
    vec={"sample_id":"s1","session_date":"2026-09-01","ticker":"SPX","decision_time":"2026-09-01T10:10:00",
         "features":{"flow_surprise_flow_surprise_state":"HIGH"},"feature_availability":{"flow_surprise_flow_surprise_state":"2026-09-01T10:10:00"},
         "max_feature_lag_seconds":0,"feature_count":1,"schema_version":"test"}
    assert feature_store_db.write_features(vec) is True
    vec["features"]["flow_surprise_flow_surprise_state"]="NORMAL"
    assert feature_store_db.write_features(vec) is False
    assert feature_store_db.get_features("s1")["features"]["flow_surprise_flow_surprise_state"] == "HIGH"


def _insert_gamma(path, when, net, flip=6500, z=.5, zo=.6, w=.8, durability="MEDIUM", pv="p"):
    with connect(str(path), timeout=10) as c:
        c.execute("""INSERT INTO gamma_observational_snapshots
        (ticker,observed_at,source_timestamp,source,path_version,net_gex,gamma_flip,zero_dte_share,zero_one_dte_share,weekly_gamma_share,durability,capacity_ratio,snapshot_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", ("SPX",when,when,"TEST",pv,net,flip,z,zo,w,durability,None,"{}")); c.commit()


def _current(net, when="2026-09-01T10:00:00+00:00", **kw):
    d={"ticker":"SPX","observed_at":when,"net_gex":net,"gamma_flip":kw.get("flip",6500),"zero_dte_share":kw.get("z",.5),
       "zero_one_dte_share":kw.get("zo",.6),"weekly_gamma_share":kw.get("w",.8),"durability":kw.get("durability","MEDIUM"),"path_version":kw.get("pv","p4")}
    return d


def test_gamma_transition_derivatives_and_strengthening(tmp_path):
    db=tmp_path/"g.db"; assert init_db(str(db))
    _insert_gamma(db,"2026-09-01T09:30:00+00:00",100)
    _insert_gamma(db,"2026-09-01T09:45:00+00:00",100, flip=6490, z=.40, zo=.50, w=.70, pv="p1")
    _insert_gamma(db,"2026-09-01T09:55:00+00:00",120)
    out=compute_transition(_current(150, flip=6510, z=.55, zo=.65, w=.82), db_path=str(db))
    assert out["net_gex_change_5m"] == 30
    assert out["net_gex_change_15m"] == 50
    assert out["net_gex_change_30m"] == 50
    assert out["gamma_flip_change"] == 20
    assert out["transition_state"] == "STRENGTHENING"
    assert out["execution_authority"] is False and out["automatic_calibration_activation"] is False


def test_gamma_transition_stable_weakening_and_rapid(tmp_path):
    db=tmp_path/"g.db"; assert init_db(str(db))
    _insert_gamma(db,"2026-09-01T09:45:00+00:00",100)
    _insert_gamma(db,"2026-09-01T09:55:00+00:00",100)
    assert compute_transition(_current(105),db_path=str(db))["transition_state"] == "STABLE"
    assert compute_transition(_current(80),db_path=str(db))["transition_state"] == "WEAKENING"
    assert compute_transition(_current(160),db_path=str(db))["transition_state"] == "RAPID_TRANSITION"


def test_gamma_transition_stale_or_missing_history_fails_closed(tmp_path):
    db=tmp_path/"g.db"; assert init_db(str(db))
    _insert_gamma(db,"2026-09-01T09:00:00+00:00",100)
    out=compute_transition(_current(150),db_path=str(db))
    assert out["transition_state"] == "INSUFFICIENT_HISTORY"
    assert out["net_gex_change_5m"] is None


def test_gamma_transition_decision_context_surface_is_read_only():
    state=build_dynamic_state({"gamma_transition":{"status":"AVAILABLE","transition_state":"WEAKENING","net_gex_change_15m":-10}})
    gt=state["gamma_transition"]
    assert gt["transition_state"] == "WEAKENING"
    assert gt["behavioral_authority"] is False and gt["execution_authority"] is False
