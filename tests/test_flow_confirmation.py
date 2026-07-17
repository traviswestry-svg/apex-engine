import datetime as dt
from zoneinfo import ZoneInfo

from engine.flow_confirmation import FlowConfirmationTracker, market_snapshot, signed_delta_total

ET = ZoneInfo("America/New_York")


def _event(eid, delta=0.4, agg="BUY"):
    return {"event_id": eid, "execution_aggression": agg,
            "observable_facts": {"delta": delta, "contracts": 10}}


def _cluster():
    return {"cluster_id": "c1", "member_event_ids": ["e1"], "end_time": "10:00:00",
            "start_time": "10:00:00", "number_of_prints": 2,
            "directional_interpretation": "BULLISH", "confidence": 80,
            "intent_summary": {"spread_leg_candidate": 2}}


def test_market_snapshot_extracts_instruments():
    s = market_snapshot({"market_state": {"instruments": {"SPX": {"price": 6000}, "ES": {"price": 6010}},
                                                  "liquidity_score": 88}},
                        observed_at=dt.datetime(2026, 7, 17, 10, 0, 0, tzinfo=ET))
    assert s["spx_price"] == 6000 and s["es_price"] == 6010 and s["liquidity_score"] == 88


def test_signed_delta_is_none_when_unmeasurable():
    assert signed_delta_total([{"execution_aggression": "BUY", "observable_facts": {"contracts": 2}}]) is None


def test_tracker_wires_30s_2m_price_es_delta_and_liquidity():
    tr = FlowConfirmationTracker()
    events = {"e1": _event("e1", .4)}
    b = {"observed_at": "x", "observed_at_et_seconds": 36000, "spx_price": 6000,
         "es_price": 6010, "liquidity_score": 90}
    first = tr.observe([_cluster()], events, b)[0]
    assert first["flow_authenticity"]["state"].endswith("PENDING_CONFIRMATION")

    # New flow has more positive signed delta at 30 seconds.
    events["e1"] = _event("e1", .5)
    tr.observe([_cluster()], events, dict(b, observed_at_et_seconds=36031, spx_price=6001))[0]
    events["e1"] = _event("e1", .6)
    final = tr.observe([_cluster()], events, dict(b, observed_at_et_seconds=36121,
                       spx_price=6002, es_price=6012, liquidity_score=84))[0]
    c = final["post_cluster_confirmation"]["confirmation"]
    assert c == {"flow_persistence_30s": True, "flow_persistence_2m": True,
                 "price_response_after_cluster": True, "es_confirmation": True,
                 "liquidity_response": True}
    assert final["flow_authenticity"]["state"] == "SCHEDULED_FLOW_CONFIRMED_DIRECTIONAL"


def test_missing_delta_and_liquidity_remain_none():
    tr = FlowConfirmationTracker()
    events = {"e1": {"event_id": "e1", "execution_aggression": "BUY",
                     "observable_facts": {"contracts": 10}}}
    b = {"observed_at": "x", "observed_at_et_seconds": 36000, "spx_price": 6000,
         "es_price": None, "liquidity_score": None}
    tr.observe([_cluster()], events, b)
    out = tr.observe([_cluster()], events, dict(b, observed_at_et_seconds=36121, spx_price=6001))[0]
    c = out["post_cluster_confirmation"]["confirmation"]
    assert c["flow_persistence_30s"] is None
    assert c["flow_persistence_2m"] is None
    assert c["es_confirmation"] is None
    assert c["liquidity_response"] is None
