"""Tests for engine/premium_chain_pricing.py + the premium engine's use of it.

The regression that motivated this: APEX alerted an SPX iron condor as
"Net credit 3.30 · Max profit $330 · Max loss $670". The real ticket was a 0.10
DEBIT — max profit $0, max loss $1,010. Every economic field was modelled from a
full-day expected move at 1:19 PM and never checked against the chain.
"""
import datetime as dt
import zoneinfo

import pytest

from engine.premium_chain_pricing import (LIVE_BASIS, UNPRICEABLE, price_structure)
from engine.premium_strategy import (build_premium_strategy, scale_sigma_to_session,
                                     session_minutes_left)

ET = zoneinfo.ZoneInfo("America/New_York")
CONDOR = {"put_short": 7400.0, "put_long": 7390.0,
          "call_short": 7570.0, "call_long": 7580.0}

# The exact quotes from the live E*TRADE ticket.
REAL = {("PUT", 7400.0): (0.20, 0.25), ("PUT", 7390.0): (0.20, 0.25),
        ("CALL", 7570.0): (0.10, 0.15), ("CALL", 7580.0): (0.10, 0.15)}


def _fetcher(book=REAL):
    def f(symbol, expiration, side):
        return [{"strike": k, "optionType": s, "bid": b, "ask": a, "volume": 100,
                 "openInterest": 500, "greeks": {"delta": 0.05, "iv": 0.18},
                 "expiration": expiration}
                for (s, k), (b, a) in book.items() if s == side]
    return f


_UNSET = object()


def _price(book=REAL, fetcher=_UNSET, legs=None, width=10.0):
    # sentinel, not None: a test passing fetcher=None must actually get None
    return price_structure(strategy="IRON_CONDOR", legs=legs or CONDOR, symbol="SPX",
                           expiration="2026-07-17",
                           chain_fetcher=_fetcher(book) if fetcher is _UNSET else fetcher,
                           width=width)


# ── the actual regression ─────────────────────────────────────────────────
def test_the_real_ticket_prices_as_a_debit_not_a_330_credit():
    p = _price()
    assert p["available"] is True
    assert p["pricing_basis"] == LIVE_BASIS
    assert p["entry_credit"] == -0.10        # APEX claimed +3.30
    assert p["is_credit"] is False
    assert p["max_profit"] == 0              # APEX claimed $330
    assert p["max_loss"] == 1010             # APEX claimed $670


def test_a_debit_structure_says_it_cannot_profit():
    p = _price()
    assert any("cannot profit" in w for w in p["warnings"])
    assert any("DEBIT" in w for w in p["warnings"])


def test_executable_convention_sell_at_bid_buy_at_ask():
    p = _price()
    by = {(l["action"], l["side"], l["strike"]): l["price"] for l in p["legs_priced"]}
    assert by[("SELL", "PUT", 7400.0)] == 0.20      # bid
    assert by[("BUY", "PUT", 7390.0)] == 0.25       # ask
    assert by[("SELL", "CALL", 7570.0)] == 0.10     # bid
    assert by[("BUY", "CALL", 7580.0)] == 0.15      # ask


def test_never_prices_at_mid():
    """Mid would report 0.00 — still wrong, and a price nobody fills."""
    p = _price()
    assert p["entry_credit"] != 0.00


def test_minimum_tick_shorts_are_flagged():
    p = _price()
    assert any("no sellable premium" in w for w in p["warnings"])


# ── refusing to invent ────────────────────────────────────────────────────
def test_missing_leg_makes_the_whole_structure_unpriceable():
    book = {k: v for k, v in REAL.items() if k != ("CALL", 7580.0)}
    p = _price(book)
    assert p["available"] is False
    assert p["pricing_basis"] == UNPRICEABLE
    assert any("not a cheaper spread" in w for w in p["warnings"])


def test_one_sided_market_is_unpriceable():
    book = dict(REAL); book[("CALL", 7580.0)] = (0.10, None)
    p = _price(book)
    assert p["available"] is False


def test_crossed_market_is_unpriceable():
    book = dict(REAL); book[("CALL", 7580.0)] = (0.30, 0.10)
    p = _price(book)
    assert p["available"] is False
    assert any("crossed" in w for w in p["warnings"])


def test_no_fetcher_is_unpriceable_not_modeled():
    p = _price(fetcher=None)
    assert p["available"] is False
    assert p["pricing_basis"] == UNPRICEABLE


def test_broken_fetcher_never_raises():
    def boom(symbol, expiration, side):
        raise RuntimeError("chain down")
    p = _price(fetcher=boom)
    assert p["available"] is False


def test_chain_fetched_once_per_side():
    calls = []
    def counting(symbol, expiration, side):
        calls.append(side)
        return _fetcher()(symbol, expiration, side)
    _price(fetcher=counting)
    assert sorted(calls) == ["CALL", "PUT"]      # 4 legs -> 2 fetches


def test_a_real_credit_prices_as_a_credit():
    book = {("PUT", 7400.0): (2.00, 2.10), ("PUT", 7390.0): (1.00, 1.10),
            ("CALL", 7570.0): (2.00, 2.10), ("CALL", 7580.0): (1.00, 1.10)}
    p = _price(book)
    assert p["entry_credit"] == pytest.approx(1.80)   # (2.00-1.10)*2
    assert p["is_credit"] is True
    assert p["max_profit"] == 180
    assert p["max_loss"] == 820


# ── the time-decay bug ────────────────────────────────────────────────────
def test_session_minutes_left():
    assert session_minutes_left(dt.datetime(2026, 7, 17, 9, 30, tzinfo=ET)) == 390
    assert session_minutes_left(dt.datetime(2026, 7, 17, 13, 19, tzinfo=ET)) == 161
    assert session_minutes_left(dt.datetime(2026, 7, 17, 16, 0, tzinfo=ET)) == 0
    assert session_minutes_left(dt.datetime(2026, 7, 17, 18, 0, tzinfo=ET)) == 0
    assert session_minutes_left(None) == 390


def test_sigma_scales_with_square_root_of_remaining_time():
    """The bug: a full-day EM used at 1:19 PM inflates every ITM probability."""
    em = 84.32
    assert scale_sigma_to_session(em, dt.datetime(2026, 7, 17, 9, 30, tzinfo=ET)) == \
        pytest.approx(84.32, abs=0.01)
    mid = scale_sigma_to_session(em, dt.datetime(2026, 7, 17, 13, 19, tzinfo=ET))
    assert mid == pytest.approx(54.2, abs=0.5)      # not 84.32
    late = scale_sigma_to_session(em, dt.datetime(2026, 7, 17, 15, 45, tzinfo=ET))
    assert late < mid < 84.32


def test_sigma_at_the_close_is_zero_not_a_full_day():
    assert scale_sigma_to_session(84.32, dt.datetime(2026, 7, 17, 16, 0, tzinfo=ET)) == 0.0


def test_zero_expected_move_does_not_explode():
    assert scale_sigma_to_session(0.0, dt.datetime(2026, 7, 17, 13, 19, tzinfo=ET)) == 0.0


# ── the engine's use of it ────────────────────────────────────────────────
_LR = {"institutional_intelligence": {"ici": 60, "grade": "B", "pin_probability": 70,
                                      "gamma_regime": "POSITIVE_GAMMA",
                                      "auction_state": "BALANCED"},
       "market_state": {"price": 7486.43, "vix": 17.88},
       "range_projection": {"expected_move": 84.32},
       "volatility": {"regime": "NORMAL", "iv_rank": 30},
       "gamma": {"call_wall": 7600, "put_wall": 7350, "zero_gamma": 7480,
                 "regime": "POSITIVE_GAMMA", "pin_probability": 70},
       "auction": {"state": "BALANCED"}}
_CONF = {"dominant_side": "NEITHER", "conviction": "NONE"}
_NOW = dt.datetime(2026, 7, 17, 13, 19, tzinfo=ET)


def _rich_book():
    """A chain that supports a genuine credit at any strike the model picks."""
    book = {}
    for k in range(7200, 7801, 5):
        book[("PUT", float(k))] = (2.00, 2.10)
        book[("CALL", float(k))] = (2.00, 2.10)
    for k in range(7200, 7801, 5):   # long wings cheaper
        if k <= 7440 or k >= 7540:
            book[("PUT", float(k))] = (1.00, 1.10)
            book[("CALL", float(k))] = (1.00, 1.10)
    return book


def test_without_a_chain_the_engine_refuses_to_publish_economics():
    """Selection is a legitimate model conclusion; PRICING is not. The structure
    survives as a candidate, its economics do not, and it is not tradeable."""
    r = build_premium_strategy(_LR, confluence=_CONF, chain_fetcher=None, now_et=_NOW,
                               symbol="SPX", expiration="2026-07-17")
    assert "UNPRICEABLE" in r["case"]
    assert r["tradeable"] is False
    assert r["economics_available"] is False
    legs = r.get("legs") or {}
    for banned in ("entry_credit", "max_profit", "max_loss", "risk_reward", "pop"):
        assert banned not in legs, f"{banned} must not survive without a chain price"
    # the strikes DO survive — they are a proposal, not a claim
    assert legs.get("put_short") and legs.get("call_short")


def test_unpriceable_still_explains_itself():
    r = build_premium_strategy(_LR, confluence=_CONF, chain_fetcher=None, now_et=_NOW,
                               symbol="SPX", expiration="2026-07-17")
    assert any("not verifiable" in x for x in r["reason"])


def test_thin_real_credit_is_never_tradeable():
    """The original alert's setup: strikes whose real credit is ~0."""
    r = build_premium_strategy(_LR, confluence=_CONF, chain_fetcher=_fetcher(),
                               now_et=_NOW, symbol="SPX", expiration="2026-07-17")
    assert r["tradeable"] is False
    assert "UNPRICEABLE" in r["case"] or "QUALITY_REJECT" in r["case"]


def test_a_genuine_credit_survives_and_is_chain_priced():
    r = build_premium_strategy(_LR, confluence=_CONF, chain_fetcher=_fetcher(_rich_book()),
                               now_et=_NOW, symbol="SPX", expiration="2026-07-17")
    legs = r.get("legs") or {}
    if r["strategy"] != "NO_TRADE":
        assert legs["pricing_basis"] == LIVE_BASIS
        assert legs["economics_available"] is True
        assert legs["entry_credit"] == pytest.approx(1.80)
        assert r["pricing"]["entry_credit"] == pytest.approx(1.80)


def test_chain_price_overwrites_the_model_never_averages():
    r = build_premium_strategy(_LR, confluence=_CONF, chain_fetcher=_fetcher(_rich_book()),
                               now_et=_NOW, symbol="SPX", expiration="2026-07-17")
    legs = r.get("legs") or {}
    if legs.get("economics_available"):
        modeled = legs.get("modeled_credit_for_reference")
        assert modeled is not None and modeled != legs["entry_credit"]
        assert legs["entry_credit"] == r["pricing"]["entry_credit"]


def test_strikes_move_closer_as_the_session_shortens():
    """1 sigma at 1:19 PM is ~54 pts, not ~84 — the wings must tuck in."""
    early = build_premium_strategy(_LR, confluence=_CONF, chain_fetcher=_fetcher(_rich_book()),
                                   now_et=dt.datetime(2026, 7, 17, 9, 45, tzinfo=ET),
                                   symbol="SPX", expiration="2026-07-17")
    late = build_premium_strategy(_LR, confluence=_CONF, chain_fetcher=_fetcher(_rich_book()),
                                  now_et=dt.datetime(2026, 7, 17, 15, 15, tzinfo=ET),
                                  symbol="SPX", expiration="2026-07-17")
    e, l = early.get("legs") or {}, late.get("legs") or {}
    if e.get("call_short") and l.get("call_short"):
        assert l["call_short"] < e["call_short"]
        assert l["put_short"] > e["put_short"]


def test_engine_never_raises_on_a_broken_fetcher():
    def boom(symbol, expiration, side):
        raise RuntimeError("chain down")
    r = build_premium_strategy(_LR, confluence=_CONF, chain_fetcher=boom, now_et=_NOW,
                               symbol="SPX", expiration="2026-07-17")
    assert r["available"] is True
    assert r["tradeable"] is False


def test_backwards_compatible_call_without_new_args():
    r = build_premium_strategy(_LR, confluence=_CONF)
    assert r["available"] is True
    assert r["tradeable"] is False          # no chain -> never tradeable
