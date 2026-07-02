"""engine/volatility.py — APEX 6.5 Volatility Intelligence Engine.

Derives volatility regime, IV rank approximation, term structure inference,
and expected volatility path from existing VIX data and options flow.

Data sources used (no new API calls):
  - VIX price from get_vix_price() (Polygon indices snapshot)
  - Options premium from quantdata_flow_snapshot()
  - GEX score from gamma engine
  - Flow momentum from flow_intelligence

Outputs:
  - volatility_regime (COMPRESSION / EXPANSION / ELEVATED / NORMAL)
  - iv_rank_estimate (0–100 approximation from VIX percentile)
  - term_structure (CONTANGO / BACKWARDATION / FLAT)
  - vol_skew (from put/call premium ratio)
  - expected_vol_path (EXPANDING / COMPRESSING / STABLE)
  - dealer_vega_risk (HIGH / MEDIUM / LOW)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


# Historical VIX context for IV rank approximation
# 52-week reference levels (approximate long-term ranges)
VIX_52WK_LOW  = 12.0
VIX_52WK_HIGH = 35.0
VIX_LONG_TERM_AVG = 19.0


def _estimate_iv_rank(vix: float) -> float:
    """Approximate IV rank from VIX level vs 52-week range."""
    rng = VIX_52WK_HIGH - VIX_52WK_LOW
    if rng <= 0:
        return 50.0
    rank = max(0.0, min(100.0, (vix - VIX_52WK_LOW) / rng * 100))
    return round(rank, 1)


def _estimate_iv_percentile(vix: float) -> float:
    """VIX percentile relative to long-term average."""
    if vix <= VIX_52WK_LOW:
        return 5.0
    if vix >= VIX_52WK_HIGH:
        return 95.0
    # Approximate percentile from position relative to avg
    if vix <= VIX_LONG_TERM_AVG:
        return round((vix - VIX_52WK_LOW) / (VIX_LONG_TERM_AVG - VIX_52WK_LOW) * 50, 1)
    return round(50 + (vix - VIX_LONG_TERM_AVG) / (VIX_52WK_HIGH - VIX_LONG_TERM_AVG) * 50, 1)


def build_volatility_intelligence(
    *,
    vix:             float,
    vix_prev:        float = 0.0,         # prior day's VIX for change
    gex_score:       float = 50.0,
    dealer_gamma_regime: str = "NEUTRAL_GAMMA",
    call_premium:    float = 0.0,
    put_premium:     float = 0.0,
    flow_momentum:   str = "STABLE",
    minutes_open:    int = 0,
    session_state:   str = "MARKET_OPEN",
) -> Dict[str, Any]:
    """Derive volatility intelligence from VIX + existing engine data."""

    vix_v      = _sf(vix)
    vix_prev_v = _sf(vix_prev) or vix_v
    vix_chg    = vix_v - vix_prev_v
    vix_chg_pct = round((vix_chg / vix_prev_v * 100) if vix_prev_v > 0 else 0.0, 2)

    total_prem = call_premium + put_premium or 1.0
    put_ratio  = put_premium / total_prem

    iv_rank       = _estimate_iv_rank(vix_v)
    iv_percentile = _estimate_iv_percentile(vix_v)

    # ── Volatility regime ──────────────────────────────────────────────────
    if vix_v < 14:
        regime = "COMPRESSION"
        regime_note = (
            f"Volatility is compressed (VIX {vix_v:.1f}). IV rank: {iv_rank:.0f}%. "
            "Dealers are collecting premium efficiently. "
            "Low volatility favors neutral and bullish strategies. "
            "Compression often precedes expansion — monitor for catalysts."
        )
        expected_next = "EXPANSION"
    elif vix_v < 18:
        regime = "NORMAL"
        regime_note = (
            f"Volatility is in the normal range (VIX {vix_v:.1f}). IV rank: {iv_rank:.0f}%. "
            "Dealer vega exposure is manageable. "
            "Standard institutional strategies are active."
        )
        expected_next = "STABLE"
    elif vix_v < 25:
        regime = "ELEVATED"
        regime_note = (
            f"Volatility is elevated (VIX {vix_v:.1f}). IV rank: {iv_rank:.0f}%. "
            "Dealers carry significant short vega exposure. "
            "Implied volatility premium makes option buying expensive. "
            "Directional plays should favor defined-risk structures."
        )
        expected_next = "COMPRESSION" if flow_momentum == "DECREASING" else "STABLE"
    else:
        regime = "EXPANSION"
        regime_note = (
            f"Volatility is in expansion (VIX {vix_v:.1f}). IV rank: {iv_rank:.0f}%. "
            "Dealers face accelerating losses on short vega. Forced hedging amplifies moves. "
            "High-risk environment — reduce position size and widen stops."
        )
        expected_next = "COMPRESSION"

    # ── Term structure inference ────────────────────────────────────────────
    # Without live term structure data, infer from VIX level and regime
    if vix_v > 22 and dealer_gamma_regime == "NEGATIVE_GAMMA":
        term_structure = "BACKWARDATION"
        term_note = (
            "Elevated VIX with negative gamma suggests front-month IV premium over deferred. "
            "Backwardation indicates near-term fear dominates — market pricing in immediate risk."
        )
    elif vix_v < 16 and regime == "COMPRESSION":
        term_structure = "CONTANGO"
        term_note = (
            "Low VIX environment typically shows contango — deferred IV above front-month. "
            "Premium sellers favor shorter-dated options in this regime."
        )
    else:
        term_structure = "FLAT"
        term_note = (
            "Term structure is approximately flat. "
            "No strong near-term vs. deferred volatility premium signal."
        )

    # ── Volatility skew (from put/call premium ratio) ──────────────────────
    if put_ratio > 0.6:
        vol_skew = "PUT_SKEW"
        skew_note = (
            f"Put premium at {put_ratio*100:.0f}% of total flow — downside IV elevated. "
            "Institutions are paying up for protection. "
            "Negative skew typical of SPX in normal conditions."
        )
    elif put_ratio < 0.4:
        vol_skew = "CALL_SKEW"
        skew_note = (
            f"Call premium at {(1-put_ratio)*100:.0f}% — upside IV elevated. "
            "Unusual: institutions are paying up for upside. Bullish institutional conviction."
        )
    else:
        vol_skew = "BALANCED"
        skew_note = "Put/call premium split is balanced. No significant skew detected."

    # ── Expected volatility path ───────────────────────────────────────────
    if vix_chg_pct > 5 or (dealer_gamma_regime == "NEGATIVE_GAMMA" and flow_momentum == "INCREASING"):
        expected_vol_path = "EXPANDING"
        vol_path_note = (
            f"VIX {'rose' if vix_chg > 0 else 'is'} {abs(vix_chg_pct):.1f}% {'above prior close' if vix_chg_pct > 0 else ''}. "
            f"{'Negative gamma is amplifying moves. ' if dealer_gamma_regime == 'NEGATIVE_GAMMA' else ''}"
            "Volatility expansion is the primary risk. Widen stops."
        )
    elif vix_chg_pct < -5 or (dealer_gamma_regime == "POSITIVE_GAMMA" and regime in ("ELEVATED", "EXPANSION")):
        expected_vol_path = "COMPRESSING"
        vol_path_note = (
            f"VIX {'fell' if vix_chg < 0 else 'may compress'} {abs(vix_chg_pct):.1f}%. "
            f"{'Positive gamma is actively suppressing volatility. ' if dealer_gamma_regime == 'POSITIVE_GAMMA' else ''}"
            "Volatility compression favors premium sellers and range strategies."
        )
    else:
        expected_vol_path = "STABLE"
        vol_path_note = "Volatility appears stable. No strong expansion or compression signal."

    # ── Dealer vega risk ───────────────────────────────────────────────────
    vega_prem_m = total_prem / 1_000_000 if total_prem else 0
    if vix_v >= 22 and vega_prem_m > 1_000:
        dealer_vega_risk = "HIGH"
        vega_risk_note = (
            f"High dealer vega risk: VIX {vix_v:.1f} with {vega_prem_m:.0f}M in total premium. "
            "Dealers face significant losses if volatility spikes further. "
            "This can trigger forced hedging and accelerate directional moves."
        )
    elif vix_v >= 16 or vega_prem_m > 200:
        dealer_vega_risk = "MEDIUM"
        vega_risk_note = (
            f"Moderate dealer vega risk: VIX {vix_v:.1f}, {vega_prem_m:.0f}M premium. "
            "Standard exposure management expected."
        )
    else:
        dealer_vega_risk = "LOW"
        vega_risk_note = (
            f"Low dealer vega risk: VIX {vix_v:.1f} in compression. "
            "Dealers are collecting premium efficiently with limited forced hedging."
        )

    # ── Vol intelligence summary ───────────────────────────────────────────
    vol_summary = (
        f"VIX {vix_v:.1f} ({regime.lower()}, IV rank ~{iv_rank:.0f}%). "
        f"Term structure: {term_structure.lower()}. "
        f"Expected path: {expected_vol_path.lower()}. "
        f"Dealer vega risk: {dealer_vega_risk.lower()}. "
        f"{vol_path_note}"
    )

    return {
        "available":          True,
        "version":            "1.0",
        # Core readings
        "vix":                round(vix_v, 2),
        "vix_change":         round(vix_chg, 2),
        "vix_change_pct":     round(vix_chg_pct, 2),
        "iv_rank_estimate":   iv_rank,
        "iv_percentile":      iv_percentile,
        # Classification
        "regime":             regime,
        "regime_note":        regime_note,
        "expected_next":      expected_next,
        "term_structure":     term_structure,
        "term_note":          term_note,
        "vol_skew":           vol_skew,
        "skew_note":          skew_note,
        # Path
        "expected_vol_path":  expected_vol_path,
        "vol_path_note":      vol_path_note,
        # Dealer
        "dealer_vega_risk":   dealer_vega_risk,
        "vega_risk_note":     vega_risk_note,
        # Summary
        "vol_summary":        vol_summary,
    }
