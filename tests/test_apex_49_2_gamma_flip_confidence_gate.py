from engine.gamma import _calculate_zero_gamma_details
from engine.daily_key_levels import FEED_REQUIRED, GammaRegime, GammaStructure, trade_map


def test_one_sided_curve_does_not_publish_false_active_flip():
    rows = {float(k): {"net": -1.0, "call": 0.0, "put": -1.0}
            for k in range(6900, 7710, 10)}
    result = _calculate_zero_gamma_details(rows, 7316.0)
    assert result["active_gamma_flip"] is None
    assert result["gamma_flip_candidate"] is not None
    assert result["active_confidence"] == "UNAVAILABLE"
    assert result["local_crossing_count"] == 0


def test_real_local_crossing_is_publishable():
    rows = {
        7290.0: {"net": -3.0, "call": 0.0, "put": -3.0},
        7300.0: {"net": 5.0, "call": 5.0, "put": 0.0},
        7310.0: {"net": 1.0, "call": 1.0, "put": 0.0},
    }
    result = _calculate_zero_gamma_details(rows, 7300.0)
    assert result["active_gamma_flip"] is not None
    assert result["active_confidence"] == "HIGH"
    assert result["local_crossing_count"] >= 1


def test_trade_map_uses_regime_instead_of_inferring_from_unconfirmed_flip():
    gamma = GammaStructure(
        flip=None, zero_gamma=None, call_wall=7600.0, put_wall=7300.0,
        hi_gamma=None, lo_gamma=None, vol_trigger=None,
        regime=GammaRegime.SHORT_GAMMA, dealer_delta=None,
    )
    lines = trade_map(7316.0, [], gamma, type("EM", (), {"upper": FEED_REQUIRED, "lower": FEED_REQUIRED})())
    text = " ".join(line.condition + " " + line.implication for line in lines)
    assert "Dealer gamma regime: SHORT" in text
    assert "dealers long gamma" not in text
