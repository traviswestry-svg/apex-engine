"""APEX 11.0C Module 8 — Confirmation Scanner.

The defining constraint: this scanner may only strengthen or weaken confidence in
an existing SPX view. It must never originate a direction or replace SPX.
"""
from engine.confirmation_scanner import scan_confirmation

_ALL_CONFIRM_BULL = {"es_change_pct": 0.4, "spy_change_pct": 0.38, "vix_change_pct": -3.0,
                     "add": 1500, "tick": 600, "rotation": "RISK_ON", "yield_change_bps": -4}
_ALL_DIVERGE_BULL = {"es_change_pct": -0.3, "vix_change_pct": 5.0, "add": -1200,
                     "rotation": "RISK_OFF", "yield_change_bps": 8}


def test_no_spx_view_stays_neutral():
    """THE hard rule: with no SPX direction, the scanner cannot form one."""
    r = scan_confirmation(spx_direction=None, assets=_ALL_CONFIRM_BULL)
    assert r["confidence_multiplier"] == 1.0
    assert r["role"] == "modifier_only"
    assert "does not form a view" in r["note"]


def test_multiplier_is_always_bounded():
    """Confirmation can nudge up a little; divergence can pull down more — but the
    scanner can never zero a trade or double it."""
    import itertools
    for spx in ("BULLISH", "BEARISH", None):
        for es, vix, add in itertools.product((-1, 1), (-5, 5), (-2000, 2000)):
            m = scan_confirmation(spx_direction=spx,
                                  assets={"es_change_pct": es, "vix_change_pct": vix,
                                          "add": add})["confidence_multiplier"]
            assert 0.75 <= m <= 1.15


def test_full_confirmation_strengthens():
    r = scan_confirmation(spx_direction="BULLISH", assets=_ALL_CONFIRM_BULL)
    assert r["confidence_multiplier"] > 1.0
    assert r["verdict"] == "STRONGLY_CONFIRMED"
    assert r["divergence_count"] == 0


def test_full_divergence_weakens():
    r = scan_confirmation(spx_direction="BULLISH", assets=_ALL_DIVERGE_BULL)
    assert r["confidence_multiplier"] < 1.0
    assert r["verdict"] == "STRONGLY_DIVERGENT"
    assert r["confirm_count"] == 0


def test_vix_is_inverted():
    """VIX up is bearish for SPX — confirms a bear view, diverges from a bull view."""
    bull = scan_confirmation(spx_direction="BULLISH", assets={"vix_change_pct": 6.0})
    bear = scan_confirmation(spx_direction="BEARISH", assets={"vix_change_pct": 6.0})
    assert bull["confidence_multiplier"] < 1.0    # VIX up diverges from bull
    assert bear["confidence_multiplier"] > 1.0    # VIX up confirms bear


def test_divergence_is_surfaced_not_hidden():
    r = scan_confirmation(spx_direction="BULLISH", assets={"es_change_pct": 0.4, "vix_change_pct": 5.0})
    assert r["headline_divergence"]
    assert r["divergence_count"] >= 1


def test_no_assets_leaves_confidence_unchanged():
    r = scan_confirmation(spx_direction="BULLISH", assets={})
    assert r["confidence_multiplier"] == 1.0
    assert r["assets_read"] == 0


def test_never_raises():
    r = scan_confirmation(spx_direction="BULLISH", assets={"es_change_pct": "garbage"})
    assert r["available"] is True
