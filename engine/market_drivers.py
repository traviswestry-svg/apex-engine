"""engine/market_drivers.py — APEX 7.0 Market Driver Engine.

Identifies which SPX constituent stocks are actually driving index movement.
Uses Polygon daily/intraday snapshots. No new data subscriptions required.

Tracks the top 20 SPX constituents by approximate index weight.
For each: price change, weighted index impact, flow bias (from heat map or
flow snapshot if available), and sector classification.

Output answers: "What is actually moving SPX today?"
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


# ── helpers ──────────────────────────────────────────────────────────────────

def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ── SPX constituent weights (approximate, as of mid-2026) ───────────────────
# Source: approximate S&P 500 weights. Update quarterly.
SPX_CONSTITUENTS: List[Dict[str, Any]] = [
    {"ticker": "NVDA",  "weight": 6.8,  "sector": "Technology",     "theme": "AI_SEMIS"},
    {"ticker": "MSFT",  "weight": 6.1,  "sector": "Technology",     "theme": "AI_MEGA_CAP"},
    {"ticker": "AAPL",  "weight": 6.5,  "sector": "Technology",     "theme": "AI_MEGA_CAP"},
    {"ticker": "AMZN",  "weight": 3.9,  "sector": "Consumer Disc",  "theme": "CLOUD_ECOMM"},
    {"ticker": "META",  "weight": 2.7,  "sector": "Communication",  "theme": "AI_MEGA_CAP"},
    {"ticker": "GOOGL", "weight": 2.0,  "sector": "Communication",  "theme": "AI_MEGA_CAP"},
    {"ticker": "GOOG",  "weight": 1.7,  "sector": "Communication",  "theme": "AI_MEGA_CAP"},
    {"ticker": "AVGO",  "weight": 2.2,  "sector": "Technology",     "theme": "AI_SEMIS"},
    {"ticker": "TSLA",  "weight": 1.5,  "sector": "Consumer Disc",  "theme": "EV_GROWTH"},
    {"ticker": "BRK.B", "weight": 1.8,  "sector": "Financials",     "theme": "VALUE"},
    {"ticker": "LLY",   "weight": 1.6,  "sector": "Healthcare",     "theme": "HEALTHCARE"},
    {"ticker": "JPM",   "weight": 1.5,  "sector": "Financials",     "theme": "BANKS"},
    {"ticker": "XOM",   "weight": 1.3,  "sector": "Energy",         "theme": "ENERGY"},
    {"ticker": "UNH",   "weight": 1.2,  "sector": "Healthcare",     "theme": "HEALTHCARE"},
    {"ticker": "V",     "weight": 1.1,  "sector": "Financials",     "theme": "PAYMENTS"},
    {"ticker": "MA",    "weight": 0.9,  "sector": "Financials",     "theme": "PAYMENTS"},
    {"ticker": "COST",  "weight": 0.8,  "sector": "Consumer Stapl", "theme": "CONSUMER"},
    {"ticker": "NFLX",  "weight": 0.7,  "sector": "Communication",  "theme": "STREAMING"},
    {"ticker": "AMD",   "weight": 0.6,  "sector": "Technology",     "theme": "AI_SEMIS"},
    {"ticker": "ORCL",  "weight": 0.6,  "sector": "Technology",     "theme": "CLOUD_AI"},
]

TOTAL_TRACKED_WEIGHT = sum(c["weight"] for c in SPX_CONSTITUENTS)


# ── Driver scoring ────────────────────────────────────────────────────────────

def _score_driver(
    ticker:     str,
    weight:     float,
    change_pct: float,
    flow_bias:  str,
    volume_rel: float,   # relative volume vs avg (1.0 = normal)
) -> Dict[str, Any]:
    """Score a single constituent's contribution to SPX movement."""
    # Weighted index impact (approximate points)
    # SPX ~7500 × weight% × change% ≈ point contribution
    spx_level_approx = 7500.0
    weighted_impact = round(spx_level_approx * (weight / 100) * (change_pct / 100), 2)

    # Driver score (0-100): magnitude × weight × vol confirmation
    magnitude = min(abs(change_pct) * 10, 100)
    vol_boost  = min(volume_rel, 3.0) / 3.0 * 20
    flow_boost = 15 if flow_bias in ("BULLISH", "BEARISH") else 0
    score      = _clamp(magnitude * (weight / 5) + vol_boost + flow_boost)

    # Direction
    if change_pct > 0.3:
        direction = "BULLISH"
    elif change_pct < -0.3:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return {
        "ticker":          ticker,
        "weight":          weight,
        "change_pct":      round(change_pct, 3),
        "weighted_impact": weighted_impact,
        "score":           round(score, 1),
        "direction":       direction,
        "flow_bias":       flow_bias,
        "volume_relative": round(volume_rel, 2),
    }


# ── Theme classification ──────────────────────────────────────────────────────

def _classify_leadership(drivers: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Classify the market leadership theme from top bullish drivers."""
    if not drivers:
        return "MIXED", "No clear leadership theme identified."

    theme_impact: Dict[str, float] = {}
    for c in SPX_CONSTITUENTS:
        for d in drivers:
            if d["ticker"] == c["ticker"] and d["direction"] == "BULLISH":
                theme = c["theme"]
                theme_impact[theme] = theme_impact.get(theme, 0) + abs(d["weighted_impact"])

    if not theme_impact:
        return "MIXED", "Broad participation without theme concentration."

    top_theme = max(theme_impact, key=theme_impact.get)
    top_impact = theme_impact[top_theme]

    theme_labels = {
        "AI_MEGA_CAP": "AI Mega-Caps",
        "AI_SEMIS":    "AI Semiconductors",
        "CLOUD_AI":    "Cloud / AI Infrastructure",
        "CLOUD_ECOMM": "Cloud / E-Commerce",
        "BANKS":       "Financials / Banks",
        "PAYMENTS":    "Payments",
        "ENERGY":      "Energy",
        "HEALTHCARE":  "Healthcare",
        "CONSUMER":    "Consumer Staples",
        "EV_GROWTH":   "EV / Growth",
        "VALUE":       "Value",
        "STREAMING":   "Streaming / Media",
    }
    label = theme_labels.get(top_theme, top_theme)
    return top_theme, label


def _classify_breadth(bullish_weight: float, bearish_weight: float, total: float) -> Tuple[str, str]:
    """Classify index breadth from weighted constituent analysis."""
    bull_pct = bullish_weight / total * 100 if total > 0 else 50
    bear_pct = bearish_weight / total * 100 if total > 0 else 50

    if bull_pct > 70:
        return "BROAD_BULLISH", "Broad bullish participation across tracked constituents."
    elif bull_pct > 55:
        return "NARROW_BULLISH", "Bullish but concentrated — a few large caps driving the index."
    elif bear_pct > 70:
        return "BROAD_BEARISH", "Broad bearish pressure across tracked constituents."
    elif bear_pct > 55:
        return "NARROW_BEARISH", "Bearish but concentrated — large caps leading the decline."
    else:
        return "MIXED", "Mixed participation — no clear bullish or bearish dominance."


# ── Main builder ──────────────────────────────────────────────────────────────

def build_market_drivers(
    *,
    snapshot_data:   Dict[str, Dict[str, Any]],   # ticker → {change_pct, volume_relative}
    heat_map_scores: Dict[str, float],             # ticker → score from scanner heat map
    flow_biases:     Dict[str, str],               # ticker → BULLISH/BEARISH/MIXED from flow
) -> Dict[str, Any]:
    """Build SPX market driver analysis from constituent snapshot data.

    Args:
        snapshot_data:   {ticker: {"change_pct": float, "volume_relative": float}}
        heat_map_scores: {ticker: 0-100 score} from scanner heat map
        flow_biases:     {ticker: "BULLISH"|"BEARISH"|"MIXED"} from flow intelligence
    """
    all_drivers: List[Dict[str, Any]] = []
    bull_weight  = 0.0
    bear_weight  = 0.0
    avail_count  = 0

    for const in SPX_CONSTITUENTS:
        tkr    = const["ticker"]
        weight = const["weight"]
        snap   = snapshot_data.get(tkr) or {}
        chg    = _sf(snap.get("change_pct"))
        vol_r  = _sf(snap.get("volume_relative"), 1.0) or 1.0
        flow   = flow_biases.get(tkr, "MIXED")

        # Use heat map score to infer flow bias if not directly available
        if flow == "MIXED":
            hm = heat_map_scores.get(tkr, 50.0)
            if hm >= 70:
                flow = "BULLISH"
            elif hm <= 35:
                flow = "BEARISH"

        if chg != 0.0 or tkr in snapshot_data:
            avail_count += 1

        d = _score_driver(tkr, weight, chg, flow, vol_r)
        all_drivers.append({**d, "sector": const["sector"], "theme": const["theme"]})

        if d["direction"] == "BULLISH":
            bull_weight += weight
        elif d["direction"] == "BEARISH":
            bear_weight += weight

    # Sort by absolute weighted impact
    all_drivers.sort(key=lambda x: abs(x["weighted_impact"]), reverse=True)

    # Top contributors
    bullish_drivers = [d for d in all_drivers if d["direction"] == "BULLISH"][:5]
    bearish_drivers = [d for d in all_drivers if d["direction"] == "BEARISH"][:5]

    # Leadership theme
    leadership_code, leadership_label = _classify_leadership(bullish_drivers)

    # Breadth
    breadth_code, breadth_note = _classify_breadth(bull_weight, bear_weight, TOTAL_TRACKED_WEIGHT)

    # Driver score (overall)
    net_impact = sum(d["weighted_impact"] for d in all_drivers)
    driver_score = _clamp(50 + net_impact * 1.5)

    # Overall bias
    if bull_weight > bear_weight * 1.5:
        market_bias = "BULLISH"
    elif bear_weight > bull_weight * 1.5:
        market_bias = "BEARISH"
    else:
        market_bias = "MIXED"

    # Interpretation sentence
    top_bull = [d["ticker"] for d in bullish_drivers[:3]]
    top_bear = [d["ticker"] for d in bearish_drivers[:2]]

    if bullish_drivers and market_bias == "BULLISH":
        interpretation = (
            f"SPX strength is being led by {', '.join(top_bull)} "
            f"({breadth_note.lower()}) under the {leadership_label} theme. "
            f"These constituents account for approximately {bull_weight:.1f}% of tracked index weight."
        )
    elif bearish_drivers and market_bias == "BEARISH":
        interpretation = (
            f"SPX weakness is being driven by {', '.join([d['ticker'] for d in bearish_drivers[:3]])}. "
            f"{breadth_note} "
            f"Bearish drivers represent approximately {bear_weight:.1f}% of tracked index weight."
        )
    else:
        interpretation = (
            f"SPX movement is mixed. "
            f"{'Bullish: ' + ', '.join(top_bull) + '. ' if top_bull else ''}"
            f"{'Bearish: ' + ', '.join(top_bear) + '. ' if top_bear else ''}"
            f"{breadth_note}"
        )

    # Story-ready sentence
    if avail_count < 5:
        story_line = f"Market driver data is limited ({avail_count}/{len(SPX_CONSTITUENTS)} constituents available)."
    else:
        story_line = interpretation

    quality_flags = []
    if avail_count < 10:
        quality_flags.append(f"LIMITED_DATA_{avail_count}_OF_{len(SPX_CONSTITUENTS)}_AVAILABLE")
    if not POLYGON_API_KEY_AVAILABLE:
        quality_flags.append("POLYGON_NOT_CONFIGURED")

    return {
        "available":              avail_count > 0,
        "version":                "7.0",
        "ticker":                 "SPX",
        "driver_score":           round(driver_score, 1),
        "market_bias":            market_bias,
        "leadership":             leadership_code,
        "leadership_label":       leadership_label,
        "breadth":                breadth_code,
        "breadth_note":           breadth_note,
        "net_index_impact_pts":   round(net_impact, 2),
        "top_bullish_drivers":    bullish_drivers,
        "top_bearish_drivers":    bearish_drivers,
        "all_drivers":            all_drivers,
        "bullish_weight_pct":     round(bull_weight, 2),
        "bearish_weight_pct":     round(bear_weight, 2),
        "constituents_available": avail_count,
        "interpretation":         interpretation,
        "story_line":             story_line,
        "quality_flags":          quality_flags,
    }


# ── Sentinel for quality flags ────────────────────────────────────────────────
# Set by app.py after import
POLYGON_API_KEY_AVAILABLE = True
