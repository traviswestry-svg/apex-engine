"""Regression tests for engine/auction_intelligence.py node notes.

This path had ZERO coverage, which is how a string-call bug ("'str' object is
not callable" — a parenthesized expression adjacent to a string literal is a
call, not concatenation) shipped on 2026-07-26 and degraded the auction
intelligence block on every RTH compose of 2026-07-28. These tests execute the
note construction for LVNs above and below price so any exception or
unrendered template in the notes fails the suite.
"""
from __future__ import annotations

from engine.auction_intelligence import build_node_intelligence, build_auction_intelligence


def _nodes():
    return build_node_intelligence(
        price=7413.43, poc=7421.0, vah=7427.0, val=7398.0,
        hvn_list=[7421.0, 7419.0, 7417.0, 7415.0],
        lvn_list=[7414.0, 7413.0, 7412.0, 7411.0],
        call_wall=7415.0, put_wall=7410.0)


def test_node_intelligence_builds_without_raising():
    out = _nodes()
    assert out.get("available") is True
    assert out.get("nodes"), "expected a non-empty nodes list"


def test_lvn_notes_render_both_sides_with_real_levels():
    out = _nodes()
    lvns = [n for n in out["nodes"] if n.get("type") == "LVN"]
    above = [n for n in lvns if n.get("dist", 0) > 0]
    below = [n for n in lvns if n.get("dist", 0) < 0]
    assert above and below, "test data must produce LVNs on both sides of price"
    for n in lvns:
        note = n.get("note", "")
        assert isinstance(note, str) and note
        # the 2026-07-27 cosmetic bug: unrendered template must never appear
        assert "{_fmt" not in note and "{level" not in note
        # the level itself must be rendered into the text
        assert f"{n['level']:,.2f}" in note
    assert any("expect a fast move to the next HVN" in n["note"] for n in above)
    assert any("price will drop quickly" in n["note"] for n in below)


def test_full_auction_intelligence_with_nodes_never_raises():
    # Real profile shape: levels nested under "levels", plus profile rows.
    profile = {
        "available": True,
        "levels": {"poc": 7421.0, "vah": 7427.0, "val": 7398.0,
                   "hvn": [7421.0, 7419.0, 7417.0], "lvn": [7414.0, 7412.0]},
        "profile": [{"price": p, "activity": 1000.0} for p in range(7388, 7497)],
    }
    out = build_auction_intelligence(
        current_profile=profile, prior_profile=None, earlier_poc=7412.0,
        current_price=7413.43, call_wall=7415.0, put_wall=7410.0,
        minutes_open=120)
    assert out.get("available") is True
    assert out.get("nodes", {}).get("available") is True
