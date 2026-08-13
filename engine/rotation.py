"""engine/rotation.py — APEX 6.5 Market Rotation Engine.

Tracks institutional capital rotation across sectors and instruments.
Uses existing daily bar data (get_daily_bars via Polygon) and heat map
scores already computed by the scanner. No new API calls.

Pillar: Market Structure Intelligence
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _pct_chg(current: float, prior: float) -> Optional[float]:
    if prior <= 0:
        return None
    return round((current - prior) / prior * 100, 3)


# ── Relative strength calculation ─────────────────────────────────────────────

def _relative_strength(closes_a: List[float], closes_b: List[float], lookback: int = 10) -> Optional[float]:
    """Return relative strength of A vs B over lookback bars. >1 = A outperforming."""
    if len(closes_a) < lookback + 1 or len(closes_b) < lookback + 1:
        return None
    try:
        a_chg = closes_a[-1] / closes_a[-lookback] if closes_a[-lookback] else 1.0
        b_chg = closes_b[-1] / closes_b[-lookback] if closes_b[-lookback] else 1.0
        return round(a_chg / b_chg, 4) if b_chg else None
    except Exception:
        return None


def build_rotation_intelligence(
    *,
    heat_map:        Dict[str, Any],    # from scanner heat map — existing scores
    flow_snapshot:   Dict[str, Any],    # net premium by ticker
    market_state:    Dict[str, Any],    # canonical state
    breadth_score:   Optional[float] = None,  # from existing IWM/SPY function
    spx_flow_score:  float = 50.0,
    spy_flow_score:  float = 50.0,
    qqq_flow_score:  float = 50.0,
    iwm_flow_score:  float = 50.0,
) -> Dict[str, Any]:
    """Derive rotation intelligence from existing scanner + flow data.

    The heat map already scores individual tickers (SPX, SPY, QQQ, IWM,
    NVDA, TSLA, etc.). This engine adds the rotation layer: which sector
    is leading, where is capital flowing, and what does it mean for SPX.
    """
    # Extract ticker scores from heat_map
    items = heat_map.get("items") or []
    ticker_scores: Dict[str, float] = {}
    ticker_actions: Dict[str, str] = {}
    for item in items:
        t = str(item.get("ticker", "")).upper()
        if t:
            ticker_scores[t]  = _sf(item.get("score"), 50.0)
            ticker_actions[t] = str(item.get("action", "WAIT"))

    spx_score  = ticker_scores.get("SPX", spx_flow_score)
    spy_score  = ticker_scores.get("SPY", spy_flow_score)
    qqq_score  = ticker_scores.get("QQQ", qqq_flow_score)
    iwm_score  = ticker_scores.get("IWM", iwm_flow_score)
    nvda_score = ticker_scores.get("NVDA", 50.0)
    tsla_score = ticker_scores.get("TSLA", 50.0)
    meta_score = ticker_scores.get("META", 50.0)
    msft_score = ticker_scores.get("MSFT", 50.0)
    aapl_score = ticker_scores.get("AAPL", 50.0)

    # ── Sector leadership ──────────────────────────────────────────────────
    large_cap_score = (spy_score + spx_score) / 2
    tech_score      = (qqq_score + nvda_score + meta_score + msft_score) / 4
    small_cap_score = iwm_score
    mega_cap_score  = (aapl_score + msft_score + nvda_score) / 3

    # Leader identification
    sector_scores = {
        "Large Cap":  large_cap_score,
        "Technology": tech_score,
        "Small Cap":  small_cap_score,
        "Mega Cap":   mega_cap_score,
    }
    leading_sector  = max(sector_scores, key=sector_scores.get)
    lagging_sector  = min(sector_scores, key=sector_scores.get)

    # ── Capital flow direction ─────────────────────────────────────────────
    # Compare QQQ vs IWM (risk-on = QQQ leads; risk-off = IWM lags)
    qqq_vs_iwm = qqq_score - iwm_score
    if qqq_vs_iwm > 15:
        rotation_type  = "GROWTH_ROTATION"
        rotation_label = "Tech / Growth Leading"
        rotation_note  = (
            f"QQQ ({qqq_score:.0f}) is outscoring IWM ({iwm_score:.0f}) by {qqq_vs_iwm:.0f} points. "
            "Institutional capital is rotating into growth and technology. "
            "This is risk-on positioning — bullish for SPX/QQQ 0DTE calls."
        )
    elif qqq_vs_iwm < -15:
        rotation_type  = "VALUE_ROTATION"
        rotation_label = "Small Cap / Value Leading"
        rotation_note  = (
            f"IWM ({iwm_score:.0f}) is outscoring QQQ ({qqq_score:.0f}) by {abs(qqq_vs_iwm):.0f} points. "
            "Institutional capital is rotating into value and small caps. "
            "Breadth is improving — positive for the broad market but tech may underperform."
        )
    else:
        rotation_type  = "BALANCED_ROTATION"
        rotation_label = "Broad Market Participation"
        rotation_note  = (
            f"QQQ ({qqq_score:.0f}) and IWM ({iwm_score:.0f}) are in balance. "
            "No clear sector rotation signal. Broad market participation is the base case."
        )

    # ── Breadth read ───────────────────────────────────────────────────────
    if breadth_score is not None:
        if breadth_score >= 65:
            breadth_label = "STRONG"
            breadth_note  = (
                f"Market breadth is strong ({breadth_score:.0f}/100). "
                "IWM is outperforming SPY — institutional buying is broad-based. "
                "Bullish for sustained trend moves."
            )
        elif breadth_score >= 45:
            breadth_label = "MODERATE"
            breadth_note  = (
                f"Market breadth is moderate ({breadth_score:.0f}/100). "
                "Participation is reasonable but not exceptional."
            )
        else:
            breadth_label = "WEAK"
            breadth_note  = (
                f"Market breadth is weak ({breadth_score:.0f}/100). "
                "IWM is lagging SPY — leadership is narrow. "
                "Rallies in narrow markets are more fragile."
            )
    else:
        breadth_label = "UNKNOWN"
        breadth_note  = "Breadth data unavailable this cycle."

    # ── SPX implications ───────────────────────────────────────────────────
    if rotation_type == "GROWTH_ROTATION" and spx_score >= 70:
        spx_implication = (
            "Growth rotation with strong SPX flow: highest-probability environment for call entries. "
            f"Tech leading ({leading_sector}) while SPX scores {spx_score:.0f}."
        )
        spx_bias = "BULLISH"
    elif rotation_type == "VALUE_ROTATION" and spx_score >= 60:
        spx_implication = (
            "Value rotation: broader participation supports SPX even if tech underperforms. "
            "Watch for sector divergence between QQQ and SPX."
        )
        spx_bias = "MODERATELY_BULLISH"
    elif spx_score < 40:
        spx_implication = (
            f"SPX flow score ({spx_score:.0f}) is weak. Institutional flow is not supporting index-level entries. "
            "Avoid SPX directional trades until flow improves."
        )
        spx_bias = "BEARISH"
    else:
        spx_implication = (
            f"SPX flow score is neutral ({spx_score:.0f}). "
            "Wait for clear rotation signal before committing directionally."
        )
        spx_bias = "NEUTRAL"

    # ── Ranking of tracked instruments ────────────────────────────────────
    tracked = [
        ("SPX", spx_score), ("SPY", spy_score), ("QQQ", qqq_score),
        ("IWM", iwm_score), ("NVDA", nvda_score), ("TSLA", tsla_score),
        ("META", meta_score), ("MSFT", msft_score), ("AAPL", aapl_score),
    ]
    ranked = sorted(tracked, key=lambda x: x[1], reverse=True)

    # ── Rotation summary ───────────────────────────────────────────────────
    rotation_summary = (
        f"{rotation_label}: {rotation_note} "
        f"Breadth: {breadth_label.lower()}. "
        f"SPX implication: {spx_implication}"
    )

    return {
        "available":          True,
        "version":            "1.0",
        "rotation_type":      rotation_type,
        "rotation_label":     rotation_label,
        "rotation_note":      rotation_note,
        "leading_sector":     leading_sector,
        "lagging_sector":     lagging_sector,
        "sector_scores":      sector_scores,
        "breadth_label":      breadth_label,
        "breadth_score":      breadth_score,
        "breadth_note":       breadth_note,
        "spx_bias":           spx_bias,
        "spx_implication":    spx_implication,
        "ranked_instruments": ranked,
        "rotation_summary":   rotation_summary,
        # Key scores for ribbon/dashboard
        "qqq_score":  round(qqq_score, 1),
        "spx_score":  round(spx_score, 1),
        "iwm_score":  round(iwm_score, 1),
        "nvda_score": round(nvda_score, 1),
    }
