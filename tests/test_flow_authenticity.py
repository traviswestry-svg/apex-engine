from engine.flow_authenticity import assess_cluster_authenticity, clock_sync_distance_seconds


def _cluster():
    return {
        "number_of_prints": 4,
        "start_time": "11:00:05",
        "end_time": "11:00:12",
        "intent_summary": {"spread_leg_candidate": 3},
    }


def test_boundary_distance():
    assert clock_sync_distance_seconds("10:30:17") == 17
    assert clock_sync_distance_seconds("10:31:00") == 60


def test_confirmation_can_restore_but_not_overstate_directional_confidence():
    r = assess_cluster_authenticity(_cluster(), confirmation={
        "flow_persistence_30s": True,
        "flow_persistence_2m": True,
        "price_response_after_cluster": True,
        "es_confirmation": True,
        "liquidity_response": False,
    })
    assert r["state"] == "SCHEDULED_FLOW_CONFIRMED_DIRECTIONAL"
    assert 0 < r["directional_confidence_multiplier"] < 1


def test_failed_confirmation_keeps_mechanical_label():
    r = assess_cluster_authenticity(_cluster(), confirmation={
        "flow_persistence_30s": False,
        "flow_persistence_2m": False,
        "price_response_after_cluster": False,
    })
    assert r["state"] == "SCHEDULED_AUTOMATED_FLOW_UNCONFIRMED"
    assert r["directional_confidence_multiplier"] == 0.25
