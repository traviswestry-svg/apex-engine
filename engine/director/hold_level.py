"""engine/director/hold_level.py — dynamic HOLD ABOVE / HOLD BELOW engine (Part 6).

Every active position gets one deterministic level that must remain true. For a
CALL we want the strongest *support below price* to hold above; for a PUT the
strongest *resistance above price* to hold below. Candidate levels come straight
from the already-computed canonical market_state and dealer engines — no new math.

Selection is a deterministic hierarchy: score each candidate by (source strength
x proximity), then pick the best correctly-sided level. Ties break toward the
higher-strength source, then the closer level (a hold level far from price is
useless for a 0DTE scalp).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import HoldLevel


def _f(v: Any, d: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


# source -> (base strength label, base score). Higher = stronger structural level.
_SOURCE_STRENGTH = {
    "DEVELOPING_POC": ("HIGH", 100),
    "SESSION_POC":    ("HIGH", 95),
    "VWAP":           ("HIGH", 90),
    "PUT_WALL":       ("HIGH", 88),
    "CALL_WALL":      ("HIGH", 88),
    "VAL":            ("MEDIUM", 78),
    "VAH":            ("MEDIUM", 78),
    "HVN":            ("MEDIUM", 70),
    "GAMMA_FLIP":     ("MEDIUM", 68),
    "SWING_LOW":      ("MEDIUM", 66),
    "SWING_HIGH":     ("MEDIUM", 66),
    "EMA21":          ("LOW", 55),
    "EMA8":           ("LOW", 50),
    "LVN":            ("LOW", 45),
    "ENTRY_ZONE":     ("MEDIUM", 72),
}

_HUMAN = {
    "DEVELOPING_POC": "Developing POC",
    "SESSION_POC": "Session POC",
    "VWAP": "VWAP",
    "PUT_WALL": "Put Wall",
    "CALL_WALL": "Call Wall",
    "VAL": "Value Area Low",
    "VAH": "Value Area High",
    "HVN": "High Volume Node",
    "GAMMA_FLIP": "Gamma Flip",
    "SWING_LOW": "Recent Swing Low",
    "SWING_HIGH": "Recent Swing High",
    "EMA21": "EMA21 structure",
    "EMA8": "EMA8 structure",
    "LVN": "Low Volume Node",
    "ENTRY_ZONE": "Entry Zone",
}


def _atr(ms: Dict[str, Any]) -> float:
    """Best-effort ATR proxy: real ATR if present, else value-area width, else a
    small fraction of price. Only used to express distance in ATR units."""
    for k in ("atr", "atr14", "atr_5m", "atr5m"):
        v = _f(ms.get(k))
        if v and v > 0:
            return v
    vah, val = _f(ms.get("vah")), _f(ms.get("val"))
    if vah and val and vah > val:
        return (vah - val) / 2.0
    price = _f(ms.get("price"))
    if price and price > 0:
        return price * 0.0015  # ~0.15% fallback band
    return 1.0


def build_hold_level(side: str, market_state: Dict[str, Any],
                     dealer: Optional[Dict[str, Any]] = None,
                     entry_price: Optional[float] = None) -> HoldLevel:
    """Return the single dynamic hold level for an active `side` position."""
    side = (side or "").upper()
    ms = market_state or {}
    dealer = dealer or {}
    price = _f(ms.get("price"))
    if not price or side not in ("CALL", "PUT"):
        return HoldLevel(available=False, reason="No price or side for hold-level selection.")

    d_gamma = (dealer.get("gamma") or {}) if isinstance(dealer, dict) else {}

    raw = {
        "DEVELOPING_POC": _f(ms.get("developing_poc")) or _f(ms.get("poc")),
        "SESSION_POC":    _f(ms.get("poc")),
        "VWAP":           _f(ms.get("vwap")),
        "VAL":            _f(ms.get("val")),
        "VAH":            _f(ms.get("vah")),
        "HVN":            _f(ms.get("hvn")),
        "LVN":            _f(ms.get("lvn")),
        "CALL_WALL":      _f(ms.get("call_wall")) or _f(d_gamma.get("call_wall")),
        "PUT_WALL":       _f(ms.get("put_wall")) or _f(d_gamma.get("put_wall")),
        "GAMMA_FLIP":     _f(ms.get("zero_gamma")) or _f(d_gamma.get("zero_gamma")),
        "SWING_LOW":      _f(ms.get("swing_low")),
        "SWING_HIGH":     _f(ms.get("swing_high")),
        "EMA21":          _f(ms.get("ema21")),
        "EMA8":           _f(ms.get("ema8")),
        "ENTRY_ZONE":     entry_price,
    }

    atr = _atr(ms)
    want_below = side == "CALL"   # CALL holds ABOVE a support that sits below price
    candidates: List[Dict[str, Any]] = []

    for source, lvl in raw.items():
        if lvl is None or lvl <= 0:
            continue
        correctly_sided = (lvl < price) if want_below else (lvl > price)
        if not correctly_sided:
            continue
        dist = abs(price - lvl)
        dist_atr = dist / atr if atr > 0 else 0.0
        strength_label, base = _SOURCE_STRENGTH.get(source, ("LOW", 40))
        # proximity multiplier: levels within ~1 ATR are ideal; decay past that.
        prox = max(0.25, 1.0 - min(1.0, dist_atr / 3.0))
        score = base * prox
        candidates.append({
            "source": source, "label": _HUMAN.get(source, source),
            "level": round(lvl, 2), "strength": strength_label,
            "distance": round((lvl - price), 2), "distance_atr": round(dist_atr, 2),
            "score": round(score, 1),
        })

    if not candidates:
        return HoldLevel(available=False, direction="ABOVE" if want_below else "BELOW",
                         reason="No correctly-sided structural level near price.")

    candidates.sort(key=lambda c: (-c["score"], abs(c["distance"])))
    best = candidates[0]
    direction = "ABOVE" if want_below else "BELOW"
    reason = (f"{best['label']} is the nearest strong "
              f"{'support' if want_below else 'resistance'} "
              f"({best['distance_atr']} ATR {'below' if want_below else 'above'} price); "
              f"hold {direction.lower()} it while the thesis holds.")

    return HoldLevel(
        available=True, direction=direction, level=best["level"], source=best["source"],
        strength=best["strength"], distance_from_price=best["distance"],
        distance_in_atr=best["distance_atr"], reason=reason,
        candidates=candidates[:6],
    )
