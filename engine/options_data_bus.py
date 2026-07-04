"""engine/options/options_data_bus.py — normalized SPX option chain with failover.

Pulls the SPX chain from the best available source (QuantData → Polygon/Massive →
E*TRADE market API), normalizes every contract to the APEX OptionContract model, and
derives mid / spread% / liquidity score / quote staleness. The concrete fetchers are
injected by app.py so this module stays testable and free of app-level imports.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, List, Optional

from engine.execution.broker_interface import OptionContract


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _i(v: Any) -> Optional[int]:
    f = _f(v)
    return int(f) if f is not None else None


def compute_quote_metrics(bid: Optional[float], ask: Optional[float],
                          volume: Optional[int], open_interest: Optional[int],
                          quote_age_seconds: Optional[float]) -> Dict[str, Optional[float]]:
    """Derive mid, spread%, and a 0..100 liquidity score from raw quote fields."""
    mid = None
    spread_pct = None
    if bid is not None and ask is not None and ask >= bid >= 0:
        mid = round((bid + ask) / 2.0, 4)
        if mid and mid > 0:
            spread_pct = round((ask - bid) / mid * 100.0, 2)

    # Liquidity score: tighter spread + more volume/OI + fresher quote = higher.
    score = 100.0
    if spread_pct is not None:
        score -= min(60.0, spread_pct * 4.0)          # 15% spread wipes ~60 pts
    else:
        score -= 40.0
    vol = volume or 0
    oi = open_interest or 0
    if vol < 50:
        score -= 15.0
    if oi < 200:
        score -= 10.0
    if quote_age_seconds is not None and quote_age_seconds > 10:
        score -= min(20.0, (quote_age_seconds - 10))
    score = max(0.0, min(100.0, round(score, 1)))
    return {"mid": mid, "spread_pct": spread_pct, "liquidity_score": score}


def normalize_contract(raw: Dict[str, Any], *, symbol: str = "SPX",
                       source: str = "unknown",
                       now: Optional[dt.datetime] = None) -> Optional[OptionContract]:
    """Normalize one source-specific contract dict into an OptionContract.
    Accepts flexible key names so QuantData / Polygon / E*TRADE payloads all map."""
    def pick(*keys, cast=_f):
        for k in keys:
            if k in raw and raw[k] not in (None, ""):
                return cast(raw[k])
        return None

    strike = pick("strike", "strikePrice", "strike_price")
    side = str(raw.get("side") or raw.get("optionType") or raw.get("type") or "").upper()
    if side in ("C", "CALL"):
        side = "CALL"
    elif side in ("P", "PUT"):
        side = "PUT"
    if strike is None or side not in ("CALL", "PUT"):
        return None

    bid = pick("bid", "bidPrice")
    ask = pick("ask", "askPrice")
    volume = pick("volume", "totalVolume", cast=_i)
    oi = pick("open_interest", "openInterest", "oi", cast=_i)

    q_age = pick("quote_age_seconds", "quoteAge")
    if q_age is None:
        ts = raw.get("quote_time") or raw.get("timeStamp") or raw.get("quoteTime")
        if ts:
            try:
                qt = dt.datetime.fromtimestamp(float(ts) / (1000.0 if float(ts) > 1e12 else 1.0), dt.timezone.utc)
                q_age = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
                q_age = (q_age - qt).total_seconds()
            except Exception:
                q_age = None

    metrics = compute_quote_metrics(bid, ask, volume, oi, q_age)
    exp = str(raw.get("expiration") or raw.get("expiryDate") or raw.get("expiration_date") or "")

    greeks = raw.get("greeks") or raw
    osi = str(raw.get("osi_key") or raw.get("osiKey") or raw.get("symbol") or "")

    strike_i = int(strike) if float(strike).is_integer() else strike
    return OptionContract(
        symbol=symbol,
        osi_key=osi,
        display_symbol=raw.get("display_symbol") or f"{symbol} {exp} ${strike_i} {side}",
        expiration=exp, strike=strike, side=side,
        bid=bid, ask=ask, mid=metrics["mid"], last=pick("last", "lastPrice"),
        volume=volume, open_interest=oi,
        delta=_f(greeks.get("delta")), gamma=_f(greeks.get("gamma")),
        theta=_f(greeks.get("theta")), vega=_f(greeks.get("vega")),
        iv=_f(greeks.get("iv") or greeks.get("impliedVolatility") or greeks.get("volatility")),
        spread_pct=metrics["spread_pct"], liquidity_score=metrics["liquidity_score"],
        quote_age_seconds=q_age, source=source,
    )


def normalize_chain(rows: List[Dict[str, Any]], *, symbol: str = "SPX",
                    source: str = "unknown") -> List[OptionContract]:
    out: List[OptionContract] = []
    for r in rows or []:
        c = normalize_contract(r, symbol=symbol, source=source)
        if c is not None:
            out.append(c)
    return out


class OptionsDataBus:
    """Orchestrates chain retrieval across sources with a fixed failover order.

    Each fetcher is a callable (symbol, expiration_iso, side) -> list[raw dict] | None.
    Register whichever are available; the bus tries them in priority order and returns
    the first non-empty normalized result, tagging each contract with its source.
    """

    def __init__(self) -> None:
        self._fetchers: List[tuple] = []   # (source_name, callable)

    def register(self, source_name: str, fetcher: Callable[[str, str, str], Optional[List[Dict[str, Any]]]]) -> None:
        self._fetchers.append((source_name, fetcher))

    @property
    def sources(self) -> List[str]:
        return [n for n, _ in self._fetchers]

    def get_chain(self, symbol: str, expiration: str, side: str = "CALL"
                  ) -> Dict[str, Any]:
        """Return {'contracts': [...], 'source': name, 'tried': [...], 'warnings': [...]}."""
        tried: List[str] = []
        warnings: List[str] = []
        for name, fetcher in self._fetchers:
            tried.append(name)
            try:
                raw = fetcher(symbol, expiration, side)
            except Exception as e:
                warnings.append(f"{name} fetch error: {e}")
                continue
            if not raw:
                warnings.append(f"{name} returned no rows")
                continue
            contracts = normalize_chain(raw, symbol=symbol, source=name)
            contracts = [c for c in contracts if c.side == side.upper()]
            if contracts:
                contracts.sort(key=lambda c: c.strike)
                return {"contracts": [c.to_dict() for c in contracts], "source": name,
                        "tried": tried, "warnings": warnings}
        return {"contracts": [], "source": None, "tried": tried,
                "warnings": warnings or ["no source returned a usable chain"]}

    def recommend_contracts(self, contracts: List[Dict[str, Any]], *, spot: float,
                            expected_path: Optional[float] = None, side: str = "CALL",
                            max_spread_pct: float = 12.0, min_volume: int = 25,
                            n: int = 3) -> List[Dict[str, Any]]:
        """Pick near-the-money / slightly-OTM calls that pass liquidity screens.
        expected_path (a projected SPX level) nudges strike selection toward the move."""
        if not contracts or not spot:
            return []
        target = spot
        if expected_path and side == "CALL":
            target = max(spot, (spot + expected_path) / 2.0)
        elif expected_path and side == "PUT":
            target = min(spot, (spot + expected_path) / 2.0)

        def ok(c: Dict[str, Any]) -> bool:
            if c.get("side") != side:
                return False
            if c.get("bid") is None or c.get("ask") is None:
                return False
            if (c.get("spread_pct") or 999) > max_spread_pct:
                return False
            if (c.get("volume") or 0) < min_volume:
                return False
            # slightly OTM bias for calls: strike >= spot - 1 tick
            if side == "CALL" and c["strike"] < spot - 5:
                return False
            if side == "PUT" and c["strike"] > spot + 5:
                return False
            return True

        cands = [c for c in contracts if ok(c)]
        cands.sort(key=lambda c: (abs(c["strike"] - target), -(c.get("liquidity_score") or 0)))
        picks = cands[:n]
        for i, c in enumerate(picks):
            c["apex_recommendation"] = "PRIMARY" if i == 0 else "ALT"
        return picks
