from __future__ import annotations

import json
from pathlib import Path

from engine.flow_classifier import classify_flow_events
from engine.flow_clusters import build_flow_clusters
from engine.gamma_transition import compute_transition, init_db
from engine.canonical_persistence import connect
from engine.multi_horizon_transition_context import build_multi_horizon_transition_context
from engine.dynamic_state import build_dynamic_state


def _row(**over):
    r = {
        "time_et": "10:00:00", "ticker": "SPX", "contract_type": "CALL",
        "strike": 6500.0, "expiration": "2026-09-11", "premium": 100000.0,
        "trade_price": 5.0, "contracts": 100, "trade_side_code": "ABOVE_ASK",
        "consolidation_type": "SWEEP", "delta": 0.60, "gamma": 0.020,
        "implied_volatility": 0.18, "bid": 4.9, "ask": 5.1,
    }
    r.update(over)
    return r


def test_cluster_greeks_use_provider_values_and_report_concentration():
    rows = [
        _row(time_et="10:00:00", strike=6500, contracts=100, delta=.60, gamma=.020, premium=100000),
        _row(time_et="10:00:04", strike=6505, contracts=300, delta=.40, gamma=.010, premium=300000, bid=4.8, ask=5.2),
    ]
    events = classify_flow_events(rows)["events"]
    out = build_flow_clusters(events)
    c = out["clusters"][0]
    assert c["weighted_delta"] == 0.45
    assert c["weighted_gamma"] == 0.0125
    assert c["cluster_delta_exposure"] == 18000.0
    assert c["cluster_gamma_exposure"] == 500.0
    assert c["volume_concentration"] == 0.75
    assert c["strike_dispersion"] == 5.0
    assert c["gamma_concentration"] == 0.6
    assert c["greek_coverage_pct"] == 100.0
    assert c["liquidity_quality"]["state"] in {"HIGH", "MODERATE", "LOW"}
    assert "weighted_delta" not in c["unavailable_metrics"]
    assert c["cluster_greek_structure_version"] == "69.10.4"


def test_cluster_greeks_fail_closed_when_provider_omits_them():
    rows = [_row(time_et="10:00:00", delta=None, gamma=None, implied_volatility=None),
            _row(time_et="10:00:03", delta=None, gamma=None, implied_volatility=None)]
    c = build_flow_clusters(classify_flow_events(rows)["events"])["clusters"][0]
    assert c["weighted_delta"] is None
    assert c["weighted_gamma"] is None
    assert c["cluster_delta_exposure"] is None
    assert c["cluster_gamma_exposure"] is None
    assert c["gamma_concentration"] is None
    assert "weighted_gamma" in c["unavailable_metrics"]


def _insert(path, when, net, *, capacity=10.0):
    with connect(str(path), timeout=10) as c:
        c.execute("""INSERT INTO gamma_observational_snapshots
        (ticker,observed_at,source_timestamp,source,path_version,net_gex,gamma_flip,zero_dte_share,zero_one_dte_share,weekly_gamma_share,durability,capacity_ratio,snapshot_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("SPX", when, when, "TEST", "p", net, 6500, .4, .5, .7, "MEDIUM", capacity, "{}"))
        c.commit()


def test_normalized_gamma_transition_uses_prior_structure_and_exposes_1m(tmp_path):
    db = tmp_path / "g.db"
    assert init_db(str(db))
    _insert(db, "2026-09-11T09:30:00+00:00", 100, capacity=10)
    _insert(db, "2026-09-11T09:45:00+00:00", 100, capacity=10)
    _insert(db, "2026-09-11T09:55:00+00:00", 120, capacity=12)
    _insert(db, "2026-09-11T09:59:00+00:00", 140, capacity=14)
    cur = {"ticker":"SPX","observed_at":"2026-09-11T10:00:00+00:00","net_gex":150,
           "gamma_flip":6510,"zero_dte_share":.45,"zero_one_dte_share":.55,
           "weekly_gamma_share":.72,"durability":"HIGH","path_version":"p2","capacity_ratio":15}
    out = compute_transition(cur, db_path=str(db))
    assert out["net_gex_change_1m"] == 10
    assert out["net_gex_transition_ratio_1m"] == round(10/140, 6)
    assert out["net_gex_transition_ratio_5m"] == 0.25
    assert out["net_gex_transition_ratio_15m"] == 0.5
    assert out["gamma_capacity_change_15m"] == 5
    assert out["transition_magnitude_ratio"] == 0.5
    assert out["behavioral_authority"] is False


def test_multi_horizon_context_preserves_disagreement_without_authority():
    gt = {
        "status":"AVAILABLE", "net_gex_transition_ratio_1m":.12,
        "net_gex_transition_ratio_5m":.08, "net_gex_transition_ratio_15m":-.10,
        "net_gex_transition_ratio_30m":-.04,
        "net_gex_change_1m":12, "net_gex_change_5m":8,
        "net_gex_change_15m":-10, "net_gex_change_30m":-4,
    }
    out = build_multi_horizon_transition_context(gamma_transition=gt,
        flow_surprise={"status":"AVAILABLE","flow_surprise_state":"HIGH","premium_percentile":97})
    assert out["multi_horizon_disagreement"] is True
    assert out["transition_alignment"] == "DIVERGENT"
    assert out["horizons"]["1m"]["state"] == "UP"
    assert out["horizons"]["15m"]["state"] == "DOWN"
    assert out["flow_surprise"]["current_snapshot_only"] is True
    assert out["behavioral_authority"] is False
    assert out["execution_authority"] is False
    assert out["production_effect"] == "NONE"


def test_dynamic_state_exposes_multi_horizon_context_read_only():
    state = build_dynamic_state({"gamma_transition": {
        "status":"AVAILABLE", "transition_state":"STRENGTHENING",
        "net_gex_transition_ratio_1m":.06, "net_gex_transition_ratio_5m":.08,
        "net_gex_transition_ratio_15m":.12, "net_gex_transition_ratio_30m":.15,
    }})
    mh = state["multi_horizon_transition_context"]
    assert mh["available"] is True
    assert mh["transition_alignment"] == "ALIGNED_UP"
    assert mh["decision_authority"] == "NONE"


def test_release_truth_69_10_4():
    manifest = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"]
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 10, 4)
    registry = Path("config/apex_capability_registry.yaml").read_text()
    assert f"apex_version: {manifest['apex_version']}" in registry
    assert "cluster_greek_structure_multi_horizon_transition" in registry
