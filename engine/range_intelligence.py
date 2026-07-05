"""engine/range_intelligence.py — APEX 7.2 Range Intelligence Engine.

Projects probable SPX high/low ZONES for the day from prior SPX structure, ES
overnight structure (basis-adjusted), dealer positioning, auction behaviour,
volume profile, a VIX-derived expected move, strike magnets, and institutional
flow. Answers: probable high zone, probable low zone, how much of the expected
range is used, which scenario is active, whether price is near exhaustion,
whether to avoid chasing near the edge, and what would invalidate the projection.

Design rules honoured:
  * NOT a rewrite — consumes the already-composed Data Bus object
    (STATE["last_result"]); never re-fetches or recomputes existing engine output.
  * NEVER compares raw ES levels to SPX. ES is converted with the live basis
    (basis = ES_price - SPX_price;  spx_equiv = es_level - basis).
  * Zone language, not point-precise prediction. No fake certainty.
  * Every unavailable input is explicitly labelled with a quality flag.

Pure computation + optional SQLite self-evaluation. Non-fatal throughout: any
missing input degrades to a flagged, still-structured response.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

VERSION = "7.2_RANGE_INTELLIGENCE_ENGINE"
_ET = ZoneInfo("America/New_York")

SCENARIOS = (
    "BASE_CASE", "BULL_EXPANSION", "BEAR_EXPANSION", "BALANCED_ROTATION",
    "RANGE_EXHAUSTION", "WAITING_FOR_OPEN", "INSUFFICIENT_DATA",
)


# ── small helpers ─────────────────────────────────────────────────────────────

def _f(v: Any, d: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


def _u(v: Any) -> str:
    return str(v or "").upper()


def _cluster_tol(price: float) -> float:
    """Confluence tolerance in points — ~0.09% of price, floor 4 pts."""
    return max(4.0, price * 0.0009)


# ── level clustering ──────────────────────────────────────────────────────────

def _cluster(candidates: List[Tuple[str, float]], price: float, side: str
             ) -> Optional[Dict[str, Any]]:
    """Group nearby candidate levels on one side of price into the most
    convincing confluence zone. `side` is 'HIGH' (levels above) or 'LOW' (below).

    Returns {low, high, mid, members:[(label,level)], count} or None.
    """
    pts = [(lbl, lv) for (lbl, lv) in candidates if lv is not None]
    if side == "HIGH":
        pts = [(l, v) for (l, v) in pts if v >= price - 1.0]
    else:
        pts = [(l, v) for (l, v) in pts if v <= price + 1.0]
    if not pts:
        return None

    pts.sort(key=lambda x: x[1])
    tol = _cluster_tol(price)

    # build clusters of levels within `tol` of the running cluster span
    clusters: List[List[Tuple[str, float]]] = []
    cur: List[Tuple[str, float]] = [pts[0]]
    for lbl, lv in pts[1:]:
        if lv - cur[0][1] <= tol:
            cur.append((lbl, lv))
        else:
            clusters.append(cur)
            cur = [(lbl, lv)]
    clusters.append(cur)

    def score(cl: List[Tuple[str, float]]) -> Tuple[int, float]:
        mid = sum(v for _, v in cl) / len(cl)
        # prefer denser clusters, then the one nearest price (first shelf)
        return (len(cl), -abs(mid - price))

    best = max(clusters, key=score)
    lvls = [v for _, v in best]
    lo, hi = min(lvls), max(lvls)
    if hi - lo < 3.0:  # pad a single/tight level into a real zone
        pad = 3.0 - (hi - lo)
        lo -= pad / 2
        hi += pad / 2
    return {"low": round(lo, 2), "high": round(hi, 2), "mid": round((lo + hi) / 2, 2),
            "members": [(l, round(v, 2)) for l, v in best], "count": len(best)}


def _zone_confidence(zone: Dict[str, Any], *, price: float, dealer_ok: bool,
                     auction_ok: bool, flow_ok: bool, vol_calm: bool,
                     driver_ok: bool) -> int:
    """Confidence 0-100 from confluence count + confirmations. Deliberately
    capped — this is a zone, not a prediction."""
    n = zone["count"]
    conf = 45 + min(4, n) * 9              # 2 levels ~63, 3 ~72, 4+ ~81
    conf += 6 if dealer_ok else 0
    conf += 5 if auction_ok else 0
    conf += 5 if flow_ok else 0
    conf += 4 if vol_calm else 0
    conf += 4 if driver_ok else 0
    dist = abs(zone["mid"] - price)
    if dist > price * 0.012:               # far zones are less certain
        conf -= 8
    return int(max(30, min(90, conf)))


# ── main build ────────────────────────────────────────────────────────────────

def build_range_intelligence(last_result: Dict[str, Any], *, market_open: bool,
                             ticker: str = "SPX") -> Dict[str, Any]:
    """Compute the range-intelligence block from the composed Data Bus object.

    `last_result` is STATE["last_result"] (as built by /api/institutional_os).
    Returns the {version, ticker, range_intelligence:{...}} envelope.
    """
    lr = last_result or {}
    ms = lr.get("market_state") or {}
    st = lr.get("structure") or {}
    on = lr.get("overnight_game_plan") or {}
    vol = lr.get("volatility") or {}
    mags = lr.get("strike_magnets") or {}
    dealer = lr.get("dealer_positioning") or {}
    drivers = lr.get("market_drivers") or {}
    inst = lr.get("institutional_intelligence") or {}

    flags: List[str] = []

    price = _f(ms.get("price")) or _f(st.get("current_price"))
    session_state = _u(ms.get("session_state") or lr.get("session", {}).get("session_state"))

    # Cash-closed / ES-open fallback: with no live SPX quote, anchor to the prior
    # SPX cash close and treat ES structure as offsets from current ES (the way an
    # overnight game plan is built). Honest and flagged — no fabricated basis.
    _on_es = _f((lr.get("overnight_game_plan") or {}).get("es_price"))
    _prev_close = _f((lr.get("structure") or {}).get("prev_close")) or \
        _f((lr.get("overnight_game_plan") or {}).get("prior_close"))
    price_estimated = False
    if price is None and _on_es is not None and _prev_close is not None:
        price = _prev_close
        price_estimated = True
        flags.append("SPX_PRICE_ESTIMATED_FROM_PRIOR_CLOSE")

    if price is None:
        return _envelope(ticker, {
            "available": False, "active_scenario": "INSUFFICIENT_DATA",
            "interpretation": "No SPX price available yet — run a scan once ES/cash data is live to project a range.",
            "quality_flags": ["INSUFFICIENT_DATA"],
        })

    if not market_open:
        flags.append("MARKET_CLOSED_PROJECTION_ONLY")

    # ── ES/SPX basis conversion (never compare raw ES to SPX) ────────────────
    es_price = _f(on.get("es_price"))
    es_on_high = _f(on.get("overnight_high"))
    es_on_low = _f(on.get("overnight_low"))
    basis_block: Dict[str, Any]
    spx_equiv_on_high = spx_equiv_on_low = None
    if es_price is not None and (es_on_high is not None or es_on_low is not None):
        # When anchored to prior close (cash dark), basis is the ES-vs-prior-close
        # spread (carry + weekend drift); ES levels map to cash-anchored offsets.
        basis = round(es_price - price, 2)
        if es_on_high is not None:
            spx_equiv_on_high = round(es_on_high - basis, 2)
        if es_on_low is not None:
            spx_equiv_on_low = round(es_on_low - basis, 2)
        basis_block = {
            "es_available": True, "basis": basis,
            "basis_method": "ES_MINUS_PRIOR_CLOSE" if price_estimated else "ES_MINUS_SPX",
            "es_overnight_high": es_on_high, "spx_equivalent_overnight_high": spx_equiv_on_high,
            "es_overnight_low": es_on_low, "spx_equivalent_overnight_low": spx_equiv_on_low,
        }
    else:
        basis_block = {"es_available": False,
                       "quality_flags": ["ES_FEED_UNAVAILABLE_USING_SPX_ONLY"]}
        flags.append("ES_FEED_UNAVAILABLE_USING_SPX_ONLY")

    # ── previous-day + session levels ────────────────────────────────────────
    pdh = _f(st.get("prev_day_high"))
    pdl = _f(st.get("prev_day_low"))
    prev_close = _f(st.get("prev_close")) or _f(on.get("prior_close"))
    sess_high = _f(st.get("session_high"))
    sess_low = _f(st.get("session_low"))
    if pdh is None or pdl is None:
        flags.append("SPX_PREVIOUS_DAY_LEVELS_UNAVAILABLE")

    vah = _f(ms.get("vah")) or _f(on.get("prior_vah"))
    val = _f(ms.get("val")) or _f(on.get("prior_val"))
    vwap = _f(ms.get("vwap"))
    poc = _f(ms.get("poc")) or _f(on.get("prior_poc"))
    call_wall = _f(ms.get("call_wall"))
    put_wall = _f(ms.get("put_wall"))
    zero_gamma = _f(ms.get("zero_gamma"))

    # ── expected move (VIX-derived; no options-chain EM exists in-system) ────
    vix = _f(vol.get("vix"))
    em_pts = em_high = em_low = None
    if vix is not None and vix > 0:
        em_pts = round(price * (vix / 100.0) / math.sqrt(252.0), 2)
        em_high = round(price + em_pts, 2)
        em_low = round(price - em_pts, 2)
        flags.append("EXPECTED_MOVE_DERIVED_FROM_VIX")
    else:
        flags.append("EXPECTED_MOVE_UNAVAILABLE")

    # ── ADR fallback range (prev-day range) ──────────────────────────────────
    adr = round(pdh - pdl, 2) if (pdh is not None and pdl is not None) else None
    adr_high = round(price + adr, 2) if adr else None
    adr_low = round(price - adr, 2) if adr else None
    if adr and em_pts is None:
        flags.append("USING_ATR_FALLBACK")

    # ── strike magnets (above/below spot) ────────────────────────────────────
    mag_list = mags.get("magnets") if isinstance(mags, dict) else (mags if isinstance(mags, list) else [])
    mags_above = [(f"Magnet {m.get('type','')}", _f(m.get("strike")))
                  for m in mag_list if _u(m.get("side")) == "ABOVE" and _f(m.get("strike"))]
    mags_below = [(f"Magnet {m.get('type','')}", _f(m.get("strike")))
                  for m in mag_list if _u(m.get("side")) == "BELOW" and _f(m.get("strike"))]

    # ── candidate levels for each side ───────────────────────────────────────
    high_candidates: List[Tuple[str, Optional[float]]] = [
        ("Previous day high", pdh),
        ("SPX-equiv ES overnight high", spx_equiv_on_high),
        ("Expected move upper", em_high),
        ("VAH", vah),
        ("Call wall", call_wall),
        ("ADR projection high", adr_high),
    ] + mags_above
    low_candidates: List[Tuple[str, Optional[float]]] = [
        ("Previous day low", pdl),
        ("SPX-equiv ES overnight low", spx_equiv_on_low),
        ("Expected move lower", em_low),
        ("VAL", val),
        ("Put wall", put_wall),
        ("ADR projection low", adr_low),
    ] + mags_below

    high_zone = _cluster([(l, v) for l, v in high_candidates if v is not None], price, "HIGH")
    low_zone = _cluster([(l, v) for l, v in low_candidates if v is not None], price, "LOW")

    if not high_zone or not low_zone:
        return _envelope(ticker, {
            "available": False,
            "active_scenario": "INSUFFICIENT_DATA" if (not high_zone and not low_zone) else "WAITING_FOR_OPEN",
            "basis_diagnostics": basis_block,
            "interpretation": "Not enough confluence to project a reliable range zone yet.",
            "quality_flags": list(dict.fromkeys(flags + ["INSUFFICIENT_DATA"])),
        })

    # ── confirmations for confidence ─────────────────────────────────────────
    gamma_regime = _u(ms.get("gamma_regime") or dealer.get("gamma_regime"))
    poc_mig = _u(ms.get("poc_migration"))
    flow_bias = _u(ms.get("flow_bias") or inst.get("flow_bias"))
    driver_bias = _u(drivers.get("bias") or drivers.get("driver_bias") or inst.get("market_driver_bias"))
    vol_regime = _u(vol.get("regime"))
    vol_calm = vol_regime in ("LOW", "NORMAL", "SUBDUED", "COMPRESSED")
    dealer_ok = gamma_regime in ("POSITIVE_GAMMA", "POSITIVE", "MIXED")
    auction_ok = _u(ms.get("auction_state")) in ("BALANCED", "ROTATIONAL", "ACCEPTING_HIGHER", "ACCEPTING_LOWER", "NEUTRAL DAY")

    hi_conf = _zone_confidence(high_zone, price=price, dealer_ok=dealer_ok, auction_ok=auction_ok,
                               flow_ok=flow_bias == "BULLISH", vol_calm=vol_calm,
                               driver_ok=driver_bias == "BULLISH")
    lo_conf = _zone_confidence(low_zone, price=price, dealer_ok=dealer_ok, auction_ok=auction_ok,
                               flow_ok=flow_bias == "BEARISH", vol_calm=vol_calm,
                               driver_ok=driver_bias == "BEARISH")

    # ── range used ───────────────────────────────────────────────────────────
    projected_range = max(1.0, high_zone["mid"] - low_zone["mid"])
    if sess_high is not None and sess_low is not None and sess_high > sess_low:
        range_used = (sess_high - sess_low) / projected_range * 100.0
        range_used_method = "SESSION_RANGE"
    else:
        # pre-RTH progress estimate from current price position in the projected band
        range_used = (price - low_zone["mid"]) / projected_range * 100.0
        range_used_method = "ESTIMATED_PRE_RTH"
        flags.append("PRE_RTH_ESTIMATE")
    range_used = int(max(0, min(140, round(range_used))))

    upside_remaining = round(high_zone["mid"] - price, 2)
    downside_remaining = round(price - low_zone["mid"], 2)
    near_high = abs(high_zone["mid"] - price) <= _cluster_tol(price) * 1.5 or price >= high_zone["low"]
    near_low = abs(price - low_zone["mid"]) <= _cluster_tol(price) * 1.5 or price <= low_zone["high"]

    # ── scenario classification ──────────────────────────────────────────────
    scenario = _classify_scenario(
        price=price, market_open=market_open, session_state=session_state,
        high_zone=high_zone, low_zone=low_zone, range_used=range_used,
        near_high=near_high, near_low=near_low, poc_mig=poc_mig, vwap=vwap, vah=vah, val=val,
        gamma_regime=gamma_regime, flow_bias=flow_bias, driver_bias=driver_bias,
        sweep_count=_f(ms.get("sweep_count"), 0) or 0, mags_above=mags_above, mags_below=mags_below,
        auction_state=_u(ms.get("auction_state")),
    )

    # ── exhaustion risk ──────────────────────────────────────────────────────
    exhaustion = _exhaustion_risk(range_used, near_high, near_low, gamma_regime,
                                  _u(ms.get("auction_state")), poc_mig)

    # ── opening context / bias / interpretation / invalidation ───────────────
    opening_context = _opening_context(price, prev_close, vah, val, on)
    bias = _bias(flow_bias, driver_bias, _u(inst.get("institutional_bias")), scenario)
    interpretation = _interpretation(scenario, high_zone, low_zone, range_used,
                                     near_high, near_low, exhaustion)
    invalidation = _invalidation(scenario)

    ri = {
        "available": True,
        "version": VERSION,
        "active_scenario": scenario,
        "projected_high_zone": {**{k: high_zone[k] for k in ("low", "high", "mid")},
                                "confidence": hi_conf,
                                "reasons": [f"{l} near {v}" for l, v in high_zone["members"]]},
        "projected_low_zone": {**{k: low_zone[k] for k in ("low", "high", "mid")},
                               "confidence": lo_conf,
                               "reasons": [f"{l} near {v}" for l, v in low_zone["members"]]},
        "range_used_percent": range_used,
        "range_used_method": range_used_method,
        "range_exhaustion_risk": exhaustion,
        "upside_remaining_points": upside_remaining,
        "downside_remaining_points": downside_remaining,
        "opening_context": opening_context,
        "bias": bias,
        "interpretation": interpretation,
        "invalidation": invalidation,
        "basis_diagnostics": basis_block,
        "expected_move": {"points": em_pts, "high": em_high, "low": em_low} if em_pts else None,
        "session_high": sess_high, "session_low": sess_low,
        "quality_flags": list(dict.fromkeys(flags)),
    }
    return _envelope(ticker, ri)


def _envelope(ticker: str, ri: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "ticker": (ticker or "SPX").upper(),
            "version": VERSION, "range_intelligence": ri}


# ── scenario / risk / context helpers ────────────────────────────────────────

def _classify_scenario(*, price, market_open, session_state, high_zone, low_zone,
                       range_used, near_high, near_low, poc_mig, vwap, vah, val,
                       gamma_regime, flow_bias, driver_bias, sweep_count,
                       mags_above, mags_below, auction_state) -> str:
    if not market_open and session_state in ("OVERNIGHT", "PREMARKET", "CLOSED", ""):
        # still return a projection, but tag the pre-open state
        if session_state in ("OVERNIGHT", "PREMARKET"):
            return "WAITING_FOR_OPEN"

    above_high = price > high_zone["high"]
    below_low = price < low_zone["low"]

    bull_pts = sum([
        above_high, poc_mig == "RISING",
        (vwap is not None and price > vwap), (vah is not None and price > vah),
        gamma_regime in ("NEGATIVE_GAMMA", "NEGATIVE"),
        flow_bias == "BULLISH", driver_bias == "BULLISH",
        sweep_count and sweep_count > 0 and flow_bias == "BULLISH",
        len(mags_above) > len(mags_below),
    ])
    bear_pts = sum([
        below_low, poc_mig == "FALLING",
        (vwap is not None and price < vwap), (val is not None and price < val),
        gamma_regime in ("NEGATIVE_GAMMA", "NEGATIVE"),
        flow_bias == "BEARISH", driver_bias == "BEARISH",
        sweep_count and sweep_count > 0 and flow_bias == "BEARISH",
        len(mags_below) > len(mags_above),
    ])

    # exhaustion takes priority when range is nearly spent at an edge
    if range_used > 85 and (near_high or near_low) and \
       gamma_regime in ("POSITIVE_GAMMA", "POSITIVE") and poc_mig in ("STABLE", "FLAT", ""):
        return "RANGE_EXHAUSTION"
    # Expansion needs SEVERAL of the listed conditions (price-position is one of
    # them, not a hard gate): acceptance beyond the zone with confirmation, OR an
    # overwhelming signal majority even while still testing the edge.
    if (above_high and bull_pts >= 3) or bull_pts >= 5:
        return "BULL_EXPANSION"
    if (below_low and bear_pts >= 3) or bear_pts >= 5:
        return "BEAR_EXPANSION"
    if abs(bull_pts - bear_pts) <= 1 and not above_high and not below_low:
        return "BALANCED_ROTATION"
    return "BASE_CASE"


def _exhaustion_risk(range_used, near_high, near_low, gamma_regime, auction_state, poc_mig) -> str:
    at_edge = near_high or near_low
    if range_used >= 85 and at_edge:
        return "HIGH"
    if range_used >= 70 and at_edge:
        return "MODERATE"
    if range_used >= 90:
        return "MODERATE"
    return "LOW"


def _opening_context(price, prev_close, vah, val, on) -> str:
    gap = None
    if prev_close is not None:
        gap = price - prev_close
    inside_value = (vah is not None and val is not None and val <= price <= vah)
    if gap is None:
        return "INSIDE_VALUE" if inside_value else "UNDETERMINED"
    direction = "GAP_UP" if gap > 1.0 else ("GAP_DOWN" if gap < -1.0 else "FLAT_OPEN")
    if direction == "FLAT_OPEN":
        return "INSIDE_VALUE" if inside_value else "FLAT_OPEN"
    zone = "INSIDE_VALUE" if inside_value else "OUTSIDE_VALUE"
    return f"{direction}_{zone}"


def _bias(flow_bias, driver_bias, inst_bias, scenario) -> str:
    votes = [b for b in (flow_bias, driver_bias, inst_bias) if b in ("BULLISH", "BEARISH")]
    bulls = votes.count("BULLISH")
    bears = votes.count("BEARISH")
    if scenario == "BULL_EXPANSION":
        return "BULLISH"
    if scenario == "BEAR_EXPANSION":
        return "BEARISH"
    if bulls > bears:
        return "BALANCED_TO_BULLISH"
    if bears > bulls:
        return "BALANCED_TO_BEARISH"
    return "BALANCED"


def _interpretation(scenario, high_zone, low_zone, range_used, near_high, near_low, exhaustion) -> str:
    hz = f"{high_zone['low']}\u2013{high_zone['high']}"
    lz = f"{low_zone['low']}\u2013{low_zone['high']}"
    if scenario == "RANGE_EXHAUSTION":
        return (f"Range is ~{range_used}% used near a projected edge with pinning conditions. "
                f"Do not chase 0DTE into the {'upper' if near_high else 'lower'} zone; "
                f"favour fades or wait for a fresh expansion trigger.")
    if scenario == "BULL_EXPANSION":
        return (f"Bull expansion: price is accepting above the projected high zone ({hz}) with "
                f"supportive structure. Upside extension is valid while POC keeps migrating higher.")
    if scenario == "BEAR_EXPANSION":
        return (f"Bear expansion: price is accepting below the projected low zone ({lz}) with "
                f"supportive structure. Downside extension is valid while POC keeps migrating lower.")
    if scenario == "WAITING_FOR_OPEN":
        return (f"Pre-RTH projection: today's likely range zones are {lz} (low) and {hz} (high). "
                f"Levels are projections, not live RTH confirmations — wait for the open.")
    if scenario == "BALANCED_ROTATION":
        return (f"Balanced rotation inside {lz} \u2013 {hz}. Trade the edges toward the mid; "
                f"avoid chasing breakouts without POC migration and flow confirmation.")
    edge = ""
    if near_high:
        edge = " Price is near the upper zone — do not chase calls without expansion confirmation."
    elif near_low:
        edge = " Price is near the lower zone — do not chase puts without expansion confirmation."
    return (f"SPX is trading inside the projected range ({lz} low, {hz} high); ~{range_used}% used."
            f"{edge}")


def _invalidation(scenario: str) -> List[str]:
    base = [
        "Price accepts above the upper projected zone with rising POC (upside expansion).",
        "Price breaks below the lower projected zone with falling POC (downside expansion).",
        "Dealer positioning flips strongly negative (gamma regime change).",
    ]
    if scenario == "BULL_EXPANSION":
        return ["POC stops migrating higher and price falls back inside the projected high zone.",
                "Call sweep pressure fades and gamma flips positive (pinning).",
                "Price loses VWAP with acceptance back inside value."]
    if scenario == "BEAR_EXPANSION":
        return ["POC stops migrating lower and price recovers back inside the projected low zone.",
                "Put sweep pressure fades and gamma flips positive (pinning).",
                "Price reclaims VWAP with acceptance back inside value."]
    if scenario == "RANGE_EXHAUSTION":
        return ["A fresh expansion trigger appears: POC migration resumes with accelerating sweeps.",
                "Price accepts beyond the edge zone rather than rejecting it."]
    return base


# ════════════════════════════════════════════════════════════════════════════
#  Self-evaluation — range_projection_history
# ════════════════════════════════════════════════════════════════════════════

_DB_PATH = os.getenv("RANGE_DB_PATH", os.getenv("DIRECTOR_DB_PATH", os.getenv("DB_PATH", "apex_tracking.db")))
_LOCK = threading.RLock()
_INIT = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_history() -> bool:
    global _INIT
    with _LOCK:
        if _INIT:
            return True
        try:
            d = os.path.dirname(_DB_PATH)
            if d:
                os.makedirs(d, exist_ok=True)
            conn = _connect()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS range_projection_history (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    date                TEXT,
                    ticker              TEXT,
                    projected_high_low  REAL,
                    projected_high_high REAL,
                    projected_low_low   REAL,
                    projected_low_high  REAL,
                    actual_high         REAL,
                    actual_low          REAL,
                    high_error_points   REAL,
                    low_error_points    REAL,
                    scenario_at_open    TEXT,
                    scenario_final      TEXT,
                    range_used_max      INTEGER,
                    created_at          TEXT,
                    UNIQUE(date, ticker)
                )
                """
            )
            conn.commit()
            conn.close()
            _INIT = True
            return True
        except Exception as e:  # pragma: no cover
            print(f"Range history DISABLED — table init failed: {e}", flush=True)
            return False


def _today_et() -> str:
    return dt.datetime.now(_ET).strftime("%Y-%m-%d")


def capture_projection(envelope: Dict[str, Any], ticker: str = "SPX") -> bool:
    """Store today's morning projection (once per date/ticker; idempotent)."""
    if not init_history():
        return False
    ri = (envelope or {}).get("range_intelligence") or {}
    if not ri.get("available"):
        return False
    hz = ri.get("projected_high_zone") or {}
    lz = ri.get("projected_low_zone") or {}
    try:
        with _LOCK:
            conn = _connect()
            conn.execute(
                """
                INSERT OR IGNORE INTO range_projection_history
                (date, ticker, projected_high_low, projected_high_high,
                 projected_low_low, projected_low_high, scenario_at_open,
                 range_used_max, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (_today_et(), ticker.upper(), hz.get("low"), hz.get("high"),
                 lz.get("low"), lz.get("high"), ri.get("active_scenario"),
                 ri.get("range_used_percent") or 0,
                 dt.datetime.now(dt.timezone.utc).isoformat()),
            )
            # keep the running max range_used for the day
            conn.execute(
                """UPDATE range_projection_history
                   SET range_used_max = MAX(COALESCE(range_used_max,0), ?)
                   WHERE date=? AND ticker=?""",
                (ri.get("range_used_percent") or 0, _today_et(), ticker.upper()),
            )
            conn.commit()
            conn.close()
        return True
    except Exception as e:  # pragma: no cover
        print(f"capture_projection failed: {e}", flush=True)
        return False


def record_actuals(ticker: str, *, actual_high: float, actual_low: float,
                   scenario_final: str = "", date: Optional[str] = None) -> bool:
    """After close, record the session's actual high/low and grade the projection."""
    if not init_history():
        return False
    date = date or _today_et()
    try:
        with _LOCK:
            conn = _connect()
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM range_projection_history WHERE date=? AND ticker=?",
                (date, ticker.upper()),
            ).fetchone()
            if not row:
                conn.close()
                return False
            # error = distance from actual extreme to nearest edge of its projected zone
            hi_err = _edge_error(actual_high, row["projected_high_low"], row["projected_high_high"])
            lo_err = _edge_error(actual_low, row["projected_low_low"], row["projected_low_high"])
            conn.execute(
                """UPDATE range_projection_history
                   SET actual_high=?, actual_low=?, high_error_points=?, low_error_points=?,
                       scenario_final=? WHERE date=? AND ticker=?""",
                (round(actual_high, 2), round(actual_low, 2), hi_err, lo_err,
                 scenario_final, date, ticker.upper()),
            )
            conn.commit()
            conn.close()
        return True
    except Exception as e:  # pragma: no cover
        print(f"record_actuals failed: {e}", flush=True)
        return False


def _edge_error(actual: float, zlow: Optional[float], zhigh: Optional[float]) -> Optional[float]:
    if actual is None or zlow is None or zhigh is None:
        return None
    if zlow <= actual <= zhigh:
        return 0.0
    return round(min(abs(actual - zlow), abs(actual - zhigh)), 2)


def history(ticker: str = "SPX", limit: int = 50) -> List[Dict[str, Any]]:
    if not init_history():
        return []
    try:
        with _LOCK:
            conn = _connect()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM range_projection_history WHERE ticker=? ORDER BY date DESC LIMIT ?",
                (ticker.upper(), int(limit)),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
    except Exception:
        return []


def scorecard(ticker: str = "SPX") -> Dict[str, Any]:
    """Average high/low error, hit rates within zone / 5 / 10 pts, best/worst scenario."""
    if not init_history():
        return {"ok": False, "reason": "history disabled"}
    try:
        with _LOCK:
            conn = _connect()
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                """SELECT * FROM range_projection_history
                   WHERE ticker=? AND actual_high IS NOT NULL""",
                (ticker.upper(),)).fetchall()]
            conn.close()
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e)}

    n = len(rows)
    if n == 0:
        return {"ok": True, "ticker": ticker.upper(), "graded_days": 0,
                "note": "No completed sessions graded yet — projections are captured "
                        "at the open and scored after the close."}

    def _errs(key):
        return [r[key] for r in rows if r.get(key) is not None]

    hi_errs, lo_errs = _errs("high_error_points"), _errs("low_error_points")
    all_errs = hi_errs + lo_errs

    def _hit_rate(thresh):
        if not all_errs:
            return None
        return round(100.0 * sum(1 for e in all_errs if e <= thresh) / len(all_errs), 1)

    # per-scenario accuracy by mean combined error
    by_scn: Dict[str, List[float]] = {}
    for r in rows:
        scn = r.get("scenario_at_open") or "UNKNOWN"
        errs = [e for e in (r.get("high_error_points"), r.get("low_error_points")) if e is not None]
        if errs:
            by_scn.setdefault(scn, []).extend(errs)
    scn_avg = {k: round(sum(v) / len(v), 2) for k, v in by_scn.items() if v}
    best = min(scn_avg, key=scn_avg.get) if scn_avg else None
    worst = max(scn_avg, key=scn_avg.get) if scn_avg else None

    return {
        "ok": True, "ticker": ticker.upper(), "graded_days": n,
        "avg_high_error_points": round(sum(hi_errs) / len(hi_errs), 2) if hi_errs else None,
        "avg_low_error_points": round(sum(lo_errs) / len(lo_errs), 2) if lo_errs else None,
        "hit_rate_within_zone_pct": _hit_rate(0.0),
        "hit_rate_within_5pts_pct": _hit_rate(5.0),
        "hit_rate_within_10pts_pct": _hit_rate(10.0),
        "best_scenario": best, "worst_scenario": worst,
        "scenario_avg_error": scn_avg,
    }
