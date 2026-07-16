"""engine/flow_pl_routes.py — APEX 9 Step 4 API surface.

Pipeline: existing tape → classifier → clusterer → **chain enrichment** → P/L.
Every stage is read-only; nothing upstream is modified and no public API changes.

CHAIN ENRICHMENT COST
---------------------
Marking needs a live quote, which the flow feed does not carry. Quotes come from
the options chain via the injected fetcher app.py already wires for the Trade
Command Center. `get_chain(symbol, expiration, side)` returns a whole chain, so
we fetch **once per (expiration, side)** and index by strike — not once per
contract. A busy multi-expiry tape therefore costs a handful of fetches, not
hundreds. Chains are cached per request.

Routes
------
GET /api/flow_pl          — cluster + member theoretical P/L.
GET /api/flow_pl/health   — versions, thresholds, store state, and the honest
                            limits of the numbers.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Dict, List, Optional, Tuple

from flask import jsonify, request

from .flow_classifier import classify_flow_events
from .flow_clusters import build_flow_clusters
from .flow_pl import (
    DEFAULT_MARK_METHOD,
    FLOW_PL_ENABLED,
    FLOW_PL_VERSION,
    MARK_METHODS,
    THEORETICAL_PL_LABEL,
    compute_cluster_pl,
    compute_event_pl,
    health as pl_health,
    is_expired,
    years_to_expiry,
)
from . import flow_pl_store


def _now_et_secs() -> Optional[int]:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
        n = _dt.datetime.now(tz)
        return n.hour * 3600 + n.minute * 60 + n.second
    except Exception:  # pragma: no cover
        return None


def _session_date() -> str:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
        return _dt.datetime.now(tz).date().isoformat()
    except Exception:  # pragma: no cover
        return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _empty(note: str) -> Dict[str, Any]:
    return {"available": False, "note": note, "clusters": [], "count": 0,
            "label": THEORETICAL_PL_LABEL, "flow_pl_version": FLOW_PL_VERSION}


class _ChainCache:
    """One chain fetch per (symbol, expiration, side), indexed by strike."""

    def __init__(self, fetcher: Optional[Callable[[str, str, str], Any]]):
        self._fetcher = fetcher
        self._cache: Dict[Tuple[str, str, str], Dict[float, Dict[str, Any]]] = {}
        self.fetches = 0
        self.warnings: List[str] = []

    def contract(self, symbol: str, expiration: str, side: str,
                 strike: Optional[float]) -> Optional[Dict[str, Any]]:
        if not self._fetcher or not expiration or strike is None or side not in ("CALL", "PUT"):
            return None
        key = (symbol, expiration, side)
        if key not in self._cache:
            index: Dict[float, Dict[str, Any]] = {}
            try:
                self.fetches += 1
                raw = self._fetcher(symbol, expiration, side)
                if raw:
                    # Reuse APEX's existing normalizer — it already derives mid,
                    # spread_pct, liquidity_score and quote age. Duplicating that
                    # logic here is exactly the drift ARCHITECTURE.md warns about.
                    from .options.options_data_bus import normalize_chain
                    for c in normalize_chain(raw, symbol=symbol, source="chain"):
                        if c.side != side:
                            continue
                        d = c.to_dict()
                        if d.get("strike") is not None:
                            index[float(d["strike"])] = d
            except Exception as e:
                self.warnings.append(f"Chain fetch failed for {symbol} {expiration} {side}: {e}")
            self._cache[key] = index
        return self._cache[key].get(float(strike))


def register_flow_pl_routes(
    app,
    *,
    flow_tape_provider: Optional[Callable[[List[str], float], Dict[str, Any]]] = None,
    chain_fetcher: Optional[Callable[[str, str, str], Any]] = None,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    default_ticker: str = "SPX",
    track: bool = True,
) -> None:
    """Attach P/L routes. All data access is injected — read-only by construction."""
    if track:
        flow_pl_store.init_db()

    @app.route("/api/flow_pl")
    def _flow_pl():
        try:
            if not FLOW_PL_ENABLED:
                return jsonify({"ok": True, "flow_pl": _empty(
                    "Flow P/L disabled (FLOW_PL_ENABLED=false).")})
            tickers = [t.strip().upper() for t in
                       (request.args.get("tickers") or default_ticker).split(",") if t.strip()]
            method = (request.args.get("method") or DEFAULT_MARK_METHOD).strip()
            if method not in MARK_METHODS:
                return jsonify({"ok": True, "flow_pl": _empty(
                    f"Unknown mark method {method!r}. Valid: {', '.join(MARK_METHODS)}.")})
            try:
                min_premium = float(request.args.get("min_premium") or 0)
            except (TypeError, ValueError):
                min_premium = 0.0

            if flow_tape_provider is None:
                return jsonify({"ok": True, "flow_pl": _empty(
                    "No flow source wired — nothing to price.")})

            tape = flow_tape_provider(tickers, min_premium) or {}
            rows = tape.get("rows") or []
            if not rows:
                p = _empty(tape.get("message") or "No flow rows available to price.")
                p["available"] = True
                p["upstream_status"] = tape.get("status")
                return jsonify({"ok": True, "tickers": tickers, "flow_pl": p})

            spot = None
            if last_result_provider:
                lr = last_result_provider() or {}
                ms = lr.get("market_state") or {}
                try:
                    spot = float(ms.get("price")) if ms.get("price") else None
                except (TypeError, ValueError):
                    spot = None

            classified = classify_flow_events(rows, spot=spot, as_of_secs=_now_et_secs())
            events_by_id = {e["event_id"]: e for e in classified["events"]}
            clustered = build_flow_clusters(classified["events"])

            cache = _ChainCache(chain_fetcher)
            session = _session_date()

            def _price(cl: Dict[str, Any]) -> Dict[str, Any]:
                members: List[Dict[str, Any]] = []
                ckey = cl.get("cluster_key") or {}
                ckey_s = f"{ckey.get('ticker')}|{ckey.get('option_type')}|" \
                         f"{ckey.get('expiration')}|{ckey.get('directional_interpretation')}"
                for eid in cl.get("member_event_ids", []):
                    ev = events_by_id.get(eid)
                    if not ev:
                        continue
                    f = ev.get("observable_facts") or {}
                    exp = f.get("expiration")
                    contract = None
                    extra: List[str] = []
                    if is_expired(exp):
                        extra.append("Contract has expired — no live quote; P/L is final and "
                                     "cannot be marked from the chain.")
                    else:
                        contract = cache.contract(f.get("ticker") or default_ticker, exp or "",
                                                  (f.get("contract_type") or "").upper(),
                                                  f.get("strike"))
                        if contract is None:
                            extra.append("No quote for this contract — it may sit outside the "
                                         "chain's strike window (default +/-5% of spot).")
                    pl = compute_event_pl(
                        ev, contract, method=method, spot=spot,
                        t_years=years_to_expiry(exp),
                    )
                    if extra:
                        pl["warnings"] = (pl.get("warnings") or []) + extra
                    if track and flow_pl_store.is_ready():
                        flow_pl_store.record_observation(
                            pl, cluster_key=ckey_s, session_date=session, spot=spot,
                            iv=(contract or {}).get("iv"))
                    members.append(pl)

                if track and flow_pl_store.is_ready():
                    exc = flow_pl_store.get_excursions([m["event_id"] for m in members
                                                        if m.get("event_id")])
                    for m in members:
                        e = exc.get(m.get("event_id"))
                        if e:
                            m.update({k: v for k, v in e.items()
                                      if k not in ("first_seen", "last_seen")})
                return compute_cluster_pl(cl, members)

            out_clusters = [_price(cl) for cl in clustered.get("clusters", [])]
            # Spec: P/L for qualifying individual events AND clusters. Singletons
            # are individual prints — skipping them would hide exactly the cases
            # that matter most (no quote, unknown side, far strikes).
            out_singles = [_price(cl) for cl in clustered.get("singletons", [])]

            out_clusters.sort(key=lambda c: -(abs(c.get("estimated_pl_dollars") or 0)))
            out_singles.sort(key=lambda c: -(abs(c.get("estimated_pl_dollars") or 0)))
            payload = {
                "available": True,
                "count": len(out_clusters),
                "clusters": out_clusters,
                "single_events": out_singles,
                "single_event_count": len(out_singles),
                "mark_method": method,
                "chain_fetches": cache.fetches,
                "chain_warnings": cache.warnings,
                "upstream_status": tape.get("status"),
                "label": THEORETICAL_PL_LABEL,
                "flow_pl_version": FLOW_PL_VERSION,
                "tracking": flow_pl_store.is_ready(),
            }
            return jsonify({"ok": True, "tickers": tickers, "flow_pl": payload})
        except Exception as e:
            return jsonify({"ok": True, "flow_pl": _empty(f"flow P/L route recovered: {e}")})

    @app.route("/api/flow_pl/health")
    def _flow_pl_health():
        try:
            h = pl_health()
            h["store"] = flow_pl_store.health()
            h["ok"] = True
            return jsonify({"ok": True, "health": h})
        except Exception as e:
            return jsonify({"ok": True, "health": {
                "ok": False, "note": f"health recovered: {e}",
                "flow_pl_version": FLOW_PL_VERSION}})
