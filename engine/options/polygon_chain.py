"""engine/options/polygon_chain.py — real SPX option chain + expirations from Polygon.

Feeds the OptionsDataBus so the Trade Command Center chain and the modeled-premium
delta come from live (15-min delayed on Options Starter) Polygon data instead of the
E*TRADE sandbox fixtures.

Pure functions with an injectable `get_json(url, params)` (app.py passes its
`safe_get_json`, which auto-adds the Polygon apiKey) and `next_page(url)` pager, so the
module is decoupled from app.py and unit-testable. Output dicts are shaped for
options_data_bus.normalize_contract() — no field renaming needed downstream.

SPX index options use underlying_ticker "I:SPX" on Polygon; contract tickers come back
as O:SPXW... (weeklys / 0DTE) and O:SPX... (AM-settled). Override the underlying via
POLYGON_OPTIONS_UNDERLYING if ever needed.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, List, Optional

_REF_URL = "https://api.polygon.io/v3/reference/options/contracts"
_SNAP_URL = "https://api.polygon.io/v3/snapshot/options"


def _today_et_iso() -> str:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return dt.date.today().isoformat()


def _ctype(side: str) -> str:
    return "put" if str(side or "").upper().startswith("P") else "call"


def fetch_expirations(
    get_json: Callable[..., Optional[dict]],
    *,
    underlying: str = "I:SPX",
    side: str = "CALL",
    max_exps: int = 40,
    next_page: Optional[Callable[[str], Optional[dict]]] = None,
    max_pages: int = 3,
) -> List[str]:
    """Distinct upcoming expiration dates (YYYY-MM-DD, ascending) for SPX options."""
    params = {
        "underlying_ticker": underlying,
        "contract_type": _ctype(side),
        "expiration_date.gte": _today_et_iso(),
        "expired": "false",
        "limit": 1000,
        "sort": "expiration_date",
        "order": "asc",
    }
    seen: List[str] = []
    data = get_json(_REF_URL, params)
    pages = 0
    while data:
        for r in (data.get("results") or []):
            e = r.get("expiration_date")
            if e and e not in seen:
                seen.append(e)
        nxt = data.get("next_url")
        pages += 1
        if not nxt or not next_page or pages >= max_pages or len(seen) >= max_exps:
            break
        data = next_page(nxt)
    seen.sort()
    return seen[:max_exps]


def _map_snapshot(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    d = r.get("details") or {}
    strike = d.get("strike_price")
    if strike is None:
        return None
    lq = r.get("last_quote") or {}
    day = r.get("day") or {}
    gk = r.get("greeks") or {}
    lt = r.get("last_trade") or {}
    return {
        "strike_price": strike,
        "type": d.get("contract_type"),               # "call"/"put" → normalized downstream
        "expiration": d.get("expiration_date"),
        "symbol": d.get("ticker"),                     # O:SPXW...
        "bid": lq.get("bid"),
        "ask": lq.get("ask"),
        # Polygon option snapshots expose quote timestamps in nanoseconds.
        # Preserve the raw value so the normalizer can compute age relative
        # to the chain fetch time instead of treating freshness as unknown.
        "last_updated": lq.get("last_updated") or lq.get("sip_timestamp"),
        "last": lt.get("price"),
        "volume": day.get("volume"),
        "open_interest": r.get("open_interest"),
        "greeks": {
            "delta": gk.get("delta"), "gamma": gk.get("gamma"),
            "theta": gk.get("theta"), "vega": gk.get("vega"),
            "iv": r.get("implied_volatility"),
        },
    }


def fetch_chain(
    get_json: Callable[..., Optional[dict]],
    expiration: str,
    side: str = "CALL",
    *,
    underlying: str = "I:SPX",
    next_page: Optional[Callable[[str], Optional[dict]]] = None,
    max_pages: int = 4,
    spot: Optional[float] = None,
    window_pct: float = 0.05,
) -> List[Dict[str, Any]]:
    """Raw contract dicts for one SPX expiration + side, ready for normalize_contract().

    When `spot` is provided, only strikes within +/- `window_pct` of spot are requested
    (near-the-money), so the table shows tradeable strikes with populated greeks instead
    of the entire deep-ITM/OTM ladder.
    """
    if not expiration:
        return []
    params = {
        "expiration_date": expiration,
        "contract_type": _ctype(side),
        "limit": 250,
        "order": "asc",
        "sort": "strike_price",
    }
    if spot and spot > 0 and window_pct > 0:
        lo = spot * (1.0 - window_pct)
        hi = spot * (1.0 + window_pct)
        params["strike_price.gte"] = int(lo)
        params["strike_price.lte"] = int(hi) + 1
    out: List[Dict[str, Any]] = []
    data = get_json(f"{_SNAP_URL}/{underlying}", params)
    pages = 0
    while data:
        for r in (data.get("results") or []):
            raw = _map_snapshot(r)
            if raw:
                out.append(raw)
        nxt = data.get("next_url")
        pages += 1
        if not nxt or not next_page or pages >= max_pages:
            break
        data = next_page(nxt)
    return out
