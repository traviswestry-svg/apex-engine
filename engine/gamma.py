from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .diagnostics import DiagnosticsTrace

INDEX_TICKERS = {"SPX", "SPXW", "I:SPX", "$SPX", "ES", "ES1!", "/ES"}


def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _round_level(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _is_index_like(ticker: str, reference_price: Optional[float] = None) -> bool:
    t = (ticker or "").upper().strip()
    ref = _safe_float(reference_price, 0.0) or 0.0
    return t in INDEX_TICKERS or ref >= 1000


def normalize_index_level_v6(value: Any, ticker: str = "SPX", reference_price: Optional[float] = None) -> Optional[float]:
    """Normalize index-level strikes/prices without silently corrupting ETF values.

    QuantData can return SPX strikes in compressed forms such as 75, 730, 735.5,
    while the live SPX/ES chart is 7000+. This function only scales index-like
    products and records power-of-ten style normalization. Examples:
      SPX 75    -> 7500
      SPX 730   -> 7300
      SPX 73.54 -> 7354
      SPX 7354  -> 7354
      SPY 730   -> 730
    """
    v = _safe_float(value, None)
    if v is None or v <= 0:
        return None

    ref = _safe_float(reference_price, 0.0) or 0.0
    if not _is_index_like(ticker, ref):
        return _round_level(v)

    original = float(v)

    # If we already have a real reference price, bring the value into that range.
    if ref >= 1000:
        for _ in range(6):
            if v >= ref * 0.45:
                break
            v *= 10.0
        for _ in range(6):
            if v <= ref * 2.20:
                break
            v /= 10.0
        return _round_level(v)

    # No reliable reference: use SPX/ES specific magnitude rules.
    # This is intentionally not used for SPY/QQQ/stock tickers.
    if original < 20:
        # Too small to be a valid SPX/ES wall. Leave unchanged for diagnostics.
        return _round_level(original)
    if original < 100:
        return _round_level(original * 100.0)
    if original < 1000:
        return _round_level(original * 10.0)
    if original > 20000:
        return _round_level(original / 10.0)
    return _round_level(original)


def _extract_ticker_data(data: Dict[str, Any], ticker: str) -> Optional[Dict[str, Any]]:
    d = data.get("data") if isinstance(data, dict) else None
    if not isinstance(d, dict):
        return None
    ticker_upper = (ticker or "").upper()
    direct = d.get(ticker) or d.get(ticker_upper)
    if isinstance(direct, dict):
        return direct
    for key, value in d.items():
        if str(key).upper() == ticker_upper and isinstance(value, dict):
            return value
    # QuantData can occasionally return SPXW while we asked for SPX.
    if ticker_upper in {"SPX", "SPXW"}:
        for key, value in d.items():
            if str(key).upper() in {"SPX", "SPXW"} and isinstance(value, dict):
                return value
    return None


def _parse_exposure_map(exposure_map: Any, ticker: str, stock_price: Optional[float]) -> Tuple[Dict[float, Dict[str, float]], List[Dict[str, Any]]]:
    by_strike: Dict[float, Dict[str, float]] = {}
    examples: List[Dict[str, Any]] = []
    if not isinstance(exposure_map, dict):
        return by_strike, examples

    for expiration, strikes in exposure_map.items():
        if not isinstance(strikes, dict):
            continue
        for strike_raw, cell in strikes.items():
            if not isinstance(cell, dict):
                continue
            raw_strike = _safe_float(strike_raw, None)
            if raw_strike is None:
                continue
            strike = normalize_index_level_v6(raw_strike, ticker=ticker, reference_price=stock_price) or raw_strike
            call_exp = _safe_float(cell.get("callExposure"), 0.0) or 0.0
            put_exp = _safe_float(cell.get("putExposure"), 0.0) or 0.0
            bucket = by_strike.setdefault(strike, {"call": 0.0, "put": 0.0, "net": 0.0})
            bucket["call"] += call_exp
            bucket["put"] += put_exp
            bucket["net"] += call_exp + put_exp
            if len(examples) < 8:
                examples.append({
                    "expiration": expiration,
                    "rawStrike": raw_strike,
                    "normalizedStrike": strike,
                    "callExposure": call_exp,
                    "putExposure": put_exp,
                })
    return by_strike, examples




def _gamma_regime_at_price(by_strike: Dict[float, Dict[str, float]], price: float) -> str:
    """Classify local dealer gamma from the nearest strike's cumulative curve."""
    cumulative = 0.0
    points = []
    for strike, vals in sorted(by_strike.items()):
        cumulative += float(vals.get("net", 0.0) or 0.0)
        points.append((strike, cumulative))
    if not points:
        return "UNKNOWN"
    _, value = min(points, key=lambda x: abs(x[0] - price))
    if value > 0:
        return "POSITIVE_GAMMA"
    if value < 0:
        return "NEGATIVE_GAMMA"
    return "TRANSITION"


def _build_gamma_path(by_strike: Dict[float, Dict[str, float]], spot: float, *,
                      active_flip: Optional[float], call_wall: Optional[float],
                      put_wall: Optional[float], high_gamma: Optional[float],
                      low_gamma: Optional[float]) -> Dict[str, Any]:
    """Build live spatial gamma context without duplicating LTPE statistics."""
    current = _gamma_regime_at_price(by_strike, spot)
    candidates = []
    for kind, price in (("gamma_flip", active_flip), ("call_wall", call_wall),
                        ("put_wall", put_wall), ("high_gamma_strike", high_gamma),
                        ("low_gamma_strike", low_gamma)):
        if price is None:
            continue
        candidates.append({"kind": kind, "price": _round_level(price),
                           "distance": round(float(price)-spot, 2),
                           "abs_distance": round(abs(float(price)-spot), 2),
                           "regime": _gamma_regime_at_price(by_strike, float(price))})
    candidates.sort(key=lambda x: x["abs_distance"])
    nearest = candidates[0] if candidates else None
    upside = [x for x in candidates if x["distance"] > 0]
    downside = [x for x in candidates if x["distance"] < 0]
    up_dest = min(upside, key=lambda x:x["distance"]) if upside else None
    down_dest = min(downside, key=lambda x:abs(x["distance"])) if downside else None
    snapshot_at = datetime.now(timezone.utc).isoformat()
    return {
        "available": bool(candidates), "current_regime": current,
        "nearest_transition": nearest, "upside_destination": up_dest,
        "downside_destination": down_dest,
        "path_levels": candidates,
        "crosses_gamma_flip_up": bool(active_flip is not None and active_flip > spot),
        "crosses_gamma_flip_down": bool(active_flip is not None and active_flip < spot),
        "path_version": "1.0",
        "level_version": "1.0",
        "generated_at": snapshot_at,
        "source_snapshot_at": snapshot_at,
    }


def _build_gamma_term_structure(curves: Dict[str, Dict[float, Dict[str, float]]], spot: float, *,
                                as_of: Optional[date] = None) -> Dict[str, Any]:
    """Summarize near-term gamma structure across expiries."""
    as_of = as_of or datetime.now(timezone.utc).date()
    ordered: List[Dict[str, Any]] = []
    for raw_expiry, curve in sorted((curves or {}).items()):
        try:
            expiry = date.fromisoformat(str(raw_expiry))
        except ValueError:
            continue
        if expiry < as_of:
            continue
        nearest_strike, nearest_bucket = min(
            ((float(k), v) for k, v in (curve or {}).items()),
            key=lambda kv: abs(kv[0] - float(spot)),
            default=(None, None),
        )
        if nearest_strike is None or not isinstance(nearest_bucket, dict):
            continue
        net = _safe_float(nearest_bucket.get("net"), None)
        if net is None:
            continue
        ordered.append({
            "expiration": expiry.isoformat(),
            "days_to_expiry": (expiry - as_of).days,
            "nearest_strike": _round_level(nearest_strike),
            "net_gamma": round(net, 4),
        })

    front = ordered[0] if ordered else None
    next_expiry = ordered[1] if len(ordered) > 1 else None
    front_net = _safe_float(front.get("net_gamma") if front else None, None)
    next_net = _safe_float(next_expiry.get("net_gamma") if next_expiry else None, None)
    zero_dte_dominance = bool(
        front and front["days_to_expiry"] == 0 and front_net is not None
        and (next_net is None or abs(front_net) >= abs(next_net))
    )
    term_divergence = bool(front_net is not None and next_net is not None and front_net * next_net < 0)
    snapshot_at = datetime.now(timezone.utc).isoformat()
    return {
        "available": bool(ordered),
        "as_of": as_of.isoformat(),
        "spot": _round_level(spot),
        "expiries": ordered,
        "front_expiry": front,
        "next_expiry": next_expiry,
        "zero_dte_dominance": zero_dte_dominance,
        "term_divergence": term_divergence,
        "near_term_fragility": bool(zero_dte_dominance and term_divergence),
        "generated_at": snapshot_at,
        "source_snapshot_at": snapshot_at,
    }

def build_gamma_from_quantdata_response(data: Dict[str, Any], ticker: str = "SPX") -> Dict[str, Any]:
    """Production gamma parser/normalizer for APEX 6.0.1.

    6.0.1a improvement:
    - Preserves the full-curve zero-gamma value as raw_zero_gamma.
    - Adds active_gamma_flip: the nearest useful intraday/local gamma reference
      around current SPX spot, derived from the same QuantData exposure curve.
    - The dashboard-facing zero_gamma uses active_gamma_flip when it has a
      usable local curve reading. Diagnostics keep both values so we never hide
      the source-derived full-curve result.
    """
    trace = DiagnosticsTrace("gamma")
    trace.add("raw_response_summary", {
        "is_dict": isinstance(data, dict),
        "top_level_keys": list(data.keys())[:12] if isinstance(data, dict) else [],
        "requestedTicker": ticker,
    })

    if not isinstance(data, dict):
        return _empty_gamma("NEUTRAL - NO GEX RETURNED", "QuantData returned no usable response.", trace)

    ticker_data = _extract_ticker_data(data, ticker)
    if not isinstance(ticker_data, dict):
        trace.add("ticker_data", {"found": False})
        return _empty_gamma("NEUTRAL - NO GEX MAP", "No exposureMap found for ticker.", trace)

    raw_stock_price = _safe_float(ticker_data.get("stockPrice"), None)
    normalized_stock_price = normalize_index_level_v6(raw_stock_price, ticker=ticker, reference_price=None) if raw_stock_price else None
    trace.add("stock_price", {
        "raw": raw_stock_price,
        "normalized": normalized_stock_price,
        "ticker": ticker,
    })

    exposure_map = ticker_data.get("exposureMap") or {}
    by_strike, examples = _parse_exposure_map(exposure_map, ticker=ticker, stock_price=normalized_stock_price)
    trace.add("strike_normalization_examples", {"examples": examples, "normalizedStrikeCount": len(by_strike)})

    if not by_strike:
        return _empty_gamma("NEUTRAL - EMPTY GEX MAP", "Exposure map contained no strike rows.", trace, normalized_stock_price)

    if not normalized_stock_price or normalized_stock_price <= 0:
        sorted_all = sorted(by_strike.keys())
        normalized_stock_price = sorted_all[len(sorted_all) // 2]
        trace.add("stock_price_fallback", {"method": "median_normalized_strike", "value": normalized_stock_price})

    # Keep the source curve wide enough for diagnostics, but do not let a far-tail
    # zero crossing become the primary intraday dashboard flip.
    band_pct = 0.15 if (ticker or "").upper() in {"SPX", "SPXW", "I:SPX", "$SPX"} else 0.12
    low_bound = normalized_stock_price * (1 - band_pct)
    high_bound = normalized_stock_price * (1 + band_pct)
    filtered = {k: v for k, v in by_strike.items() if low_bound <= k <= high_bound}
    if len(filtered) < 10:
        low_bound = normalized_stock_price * 0.75
        high_bound = normalized_stock_price * 1.25
        filtered = {k: v for k, v in by_strike.items() if low_bound <= k <= high_bound}
    if not filtered:
        filtered = by_strike
        low_bound, high_bound = min(by_strike), max(by_strike)

    calls_above = {k: v for k, v in filtered.items() if k >= normalized_stock_price}
    puts_below = {k: v for k, v in filtered.items() if k <= normalized_stock_price}
    call_pool = calls_above or filtered
    put_pool = puts_below or filtered

    call_wall = max(call_pool.items(), key=lambda kv: abs(kv[1].get("call", 0.0)))[0]
    put_wall = max(put_pool.items(), key=lambda kv: abs(kv[1].get("put", 0.0)))[0]

    zero_details = _calculate_zero_gamma_details(filtered, normalized_stock_price)
    raw_zero_gamma = zero_details["raw_zero_gamma"]
    active_gamma_flip = zero_details["active_gamma_flip"]
    gamma_flip_candidate = zero_details.get("gamma_flip_candidate")
    # Only publish a dashboard/trading gamma flip when the curve contains an
    # actual local zero crossing. A local minimum of |cumulative gamma| is useful
    # diagnostic context, but it is not a true sign change and must not be
    # promoted into an authoritative dealer-regime threshold.
    zero_gamma = active_gamma_flip

    # Curve-derived extrema are authoritative because they come directly from
    # QuantData exposure-by-strike, not aliases that may or may not be present.
    high_gamma_strike = max(filtered.items(), key=lambda kv: kv[1].get("net", 0.0))[0]
    low_gamma_strike = min(filtered.items(), key=lambda kv: kv[1].get("net", 0.0))[0]

    total_net = sum(v["net"] for v in filtered.values())
    total_abs = sum(abs(v["call"]) + abs(v["put"]) for v in filtered.values()) or 1.0
    net_ratio = total_net / total_abs
    score = max(0.0, min(100.0, 50.0 + net_ratio * 50.0))
    status = "POSITIVE GAMMA / PIN RISK" if score >= 60 else "NEGATIVE GAMMA / TREND RISK" if score <= 40 else "MIXED GAMMA"

    trace.add("zero_gamma_selection", zero_details)
    trace.add("engine_output", {
        "stockPrice": normalized_stock_price,
        "callWall": call_wall,
        "putWall": put_wall,
        "rawZeroGamma": raw_zero_gamma,
        "activeGammaFlip": active_gamma_flip,
        "gammaFlipCandidate": gamma_flip_candidate,
        "displayZeroGamma": zero_gamma,
        "highGammaStrike": high_gamma_strike,
        "lowGammaStrike": low_gamma_strike,
        "volatilityTrigger": active_gamma_flip,
        "zeroGammaMethod": zero_details.get("active_method"),
        "gexScore": round(score, 1),
        "netGammaRatio": round(net_ratio, 4),
        "filteredStrikeCount": len(filtered),
        "rawStrikeCount": len(by_strike),
        "bounds": [round(low_bound, 2), round(high_bound, 2)],
        "callPool": "above_spot" if calls_above else "fallback_all_filtered",
        "putPool": "below_spot" if puts_below else "fallback_all_filtered",
    })

    gamma_path = _build_gamma_path(filtered, normalized_stock_price,
                                   active_flip=active_gamma_flip, call_wall=call_wall,
                                   put_wall=put_wall, high_gamma=high_gamma_strike,
                                   low_gamma=low_gamma_strike)

    quality_flags: List[str] = []
    if call_wall < normalized_stock_price:
        quality_flags.append("CALL_WALL_BELOW_SPOT_FALLBACK_USED")
    if put_wall > normalized_stock_price:
        quality_flags.append("PUT_WALL_ABOVE_SPOT_FALLBACK_USED")
    if raw_zero_gamma and abs(raw_zero_gamma - normalized_stock_price) / normalized_stock_price > 0.12:
        quality_flags.append("RAW_ZERO_GAMMA_FAR_FROM_SPOT_SOURCE_CONFIRMED")
    if active_gamma_flip is not None and raw_zero_gamma != active_gamma_flip:
        quality_flags.append("ACTIVE_GAMMA_FLIP_USED_FOR_DASHBOARD")
    if active_gamma_flip is None and gamma_flip_candidate is not None:
        quality_flags.append("GAMMA_FLIP_CANDIDATE_SUPPRESSED_NO_LOCAL_CROSSING")
    if zero_details.get("candidate_confidence") in {"LOW", "MEDIUM"}:
        quality_flags.append("GAMMA_FLIP_CANDIDATE_NOT_AUTHORITATIVE")

    return {
        "gex_score": round(score, 1),
        "gex_status": status,
        "call_wall": _round_level(call_wall),
        "put_wall": _round_level(put_wall),
        "high_gamma_strike": _round_level(high_gamma_strike),
        "low_gamma_strike": _round_level(low_gamma_strike),
        # A volatility trigger is only authoritative when an actual local gamma
        # crossing exists. It is intentionally unavailable on a one-sided curve.
        "volatility_trigger": _round_level(active_gamma_flip),
        "zero_gamma": _round_level(zero_gamma),
        "active_gamma_flip": _round_level(active_gamma_flip),
        "gamma_flip_candidate": _round_level(gamma_flip_candidate),
        "raw_zero_gamma": _round_level(raw_zero_gamma),
        "stock_price": _round_level(normalized_stock_price),
        "raw_stock_price": raw_stock_price,
        "net_gamma_ratio": round(net_ratio, 4),
        "strike_count": len(filtered),
        "raw_strike_count": len(by_strike),
        "zero_gamma_method": zero_details.get("active_method"),
        "zero_gamma_confidence": zero_details.get("active_confidence"),
        "gamma_flip_candidate_method": zero_details.get("candidate_method"),
        "gamma_flip_candidate_confidence": zero_details.get("candidate_confidence"),
        "quality_flags": quality_flags,
        "gamma_path": gamma_path,
        "gex_notes": [
            f"Call wall {call_wall:.2f}",
            f"Put wall {put_wall:.2f}",
            (f"Active gamma flip {zero_gamma:.2f}" if zero_gamma is not None
             else "Active gamma flip unavailable — no local zero crossing"),
            (f"Diagnostic gamma candidate {gamma_flip_candidate:.2f}" if gamma_flip_candidate is not None
             else "Diagnostic gamma candidate unavailable"),
            f"Raw full-curve zero gamma {raw_zero_gamma:.2f}",
            f"Spot {normalized_stock_price:.2f}",
            f"Filtered strikes {len(filtered)}/{len(by_strike)} within {low_bound:.2f}-{high_bound:.2f}",
        ],
        "diagnostics": trace.to_dict(),
    }


def _calculate_zero_gamma_details(filtered: Dict[float, Dict[str, float]], spot: float) -> Dict[str, Any]:
    """Return audited full-curve and local gamma references.

    ``raw_zero_gamma`` preserves the source-curve diagnostic result. The
    dashboard-facing ``active_gamma_flip`` is emitted only when an actual zero
    crossing exists inside the local 6% trading band. A minimum-|cumulative|
    strike is retained as ``gamma_flip_candidate`` for diagnostics, but is never
    allowed to imply dealer long/short gamma by itself.
    """
    sorted_rows = sorted(filtered.items(), key=lambda kv: kv[0])
    cumulative = 0.0
    prev_strike: Optional[float] = None
    prev_cum: Optional[float] = None
    crossings: List[float] = []
    cumulative_points: List[Dict[str, float]] = []
    best_abs: Optional[float] = None
    best_zero = sorted_rows[0][0]

    for strike, vals in sorted_rows:
        cumulative += vals["net"]
        if prev_cum is not None and ((prev_cum < 0 < cumulative) or (prev_cum > 0 > cumulative) or cumulative == 0):
            crossings.append((prev_strike + strike) / 2 if prev_strike is not None else strike)
        abs_cum = abs(cumulative)
        cumulative_points.append({"strike": strike, "cumulative": cumulative, "abs": abs_cum})
        if best_abs is None or abs_cum < best_abs:
            best_abs = abs_cum
            best_zero = strike
        prev_strike = strike
        prev_cum = cumulative

    raw_zero = min(crossings, key=lambda x: abs(x - spot)) if crossings else best_zero

    local_band_pct = 0.06
    local_low = spot * (1 - local_band_pct)
    local_high = spot * (1 + local_band_pct)
    local_crossings = [x for x in crossings if local_low <= x <= local_high]
    local_points = [p for p in cumulative_points if local_low <= p["strike"] <= local_high]

    active = None
    active_method = "unavailable_no_local_zero_crossing"
    active_confidence = "UNAVAILABLE"
    candidate = None
    candidate_method = "unavailable"
    candidate_confidence = "UNAVAILABLE"

    if local_crossings:
        active = min(local_crossings, key=lambda x: abs(x - spot))
        active_method = "nearest_local_zero_crossing"
        active_confidence = "HIGH"
    elif local_points:
        best_local = min(local_points, key=lambda p: (p["abs"], abs(p["strike"] - spot)))
        candidate = best_local["strike"]
        candidate_method = "local_minimum_absolute_cumulative_gamma"
        distance_pct = abs(candidate - spot) / spot if spot else 1.0
        candidate_confidence = "MEDIUM" if distance_pct <= 0.025 else "LOW"
    else:
        candidate = raw_zero
        candidate_method = "raw_full_curve_fallback"
        candidate_confidence = "LOW"

    return {
        "raw_zero_gamma": _round_level(raw_zero),
        "active_gamma_flip": _round_level(active),
        "active_method": active_method,
        "active_confidence": active_confidence,
        "gamma_flip_candidate": _round_level(candidate),
        "candidate_method": candidate_method,
        "candidate_confidence": candidate_confidence,
        "local_band_pct": local_band_pct,
        "local_bounds": [_round_level(local_low), _round_level(local_high)],
        "crossing_count": len(crossings),
        "local_crossing_count": len(local_crossings),
        "nearest_crossings": [_round_level(x) for x in sorted(crossings, key=lambda x: abs(x - spot))[:8]],
    }


def _calculate_zero_gamma(filtered: Dict[float, Dict[str, float]], spot: float) -> float:
    return float(_calculate_zero_gamma_details(filtered, spot).get("raw_zero_gamma") or spot)


def _empty_gamma(status: str, note: str, trace: DiagnosticsTrace, stock_price: Optional[float] = None) -> Dict[str, Any]:
    return {
        "gex_score": 50.0,
        "gex_status": status,
        "call_wall": None,
        "put_wall": None,
        "zero_gamma": None,
        "active_gamma_flip": None,
        "gamma_flip_candidate": None,
        "raw_zero_gamma": None,
        "stock_price": stock_price,
        "raw_stock_price": None,
        "net_gamma_ratio": 0.0,
        "strike_count": 0,
        "raw_strike_count": 0,
        "zero_gamma_method": None,
        "zero_gamma_confidence": None,
        "gamma_flip_candidate_method": None,
        "gamma_flip_candidate_confidence": None,
        "quality_flags": ["NO_USABLE_GAMMA"],
        "gamma_path": {"available": False, "current_regime": "UNKNOWN", "path_levels": []},
        "gex_notes": [note],
        "diagnostics": trace.to_dict(),
    }
