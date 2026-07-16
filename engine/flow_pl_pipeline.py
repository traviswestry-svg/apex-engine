"""engine/flow_pl_pipeline.py — APEX 9 Step 4.1: the single flow P/L pipeline.

WHY THIS MODULE EXISTS
----------------------
Two callers need the identical sequence tape → classify → cluster → enrich from
chain → price → record:

  * `/api/flow_pl` (on demand, when someone is looking)
  * the background scanner sampler (every cycle, whether or not anyone is looking)

Implementing that twice is precisely the drift ARCHITECTURE.md warns about: the
route and the sampler would slowly disagree about what a mark means, and the
MFE/MAE history would stop matching the numbers on screen — with no test able to
see it. So the pipeline lives here once, and both callers are thin wrappers.

READ-ONLY BY CONSTRUCTION
-------------------------
Every data path (tape, chain, bus) is injected. This module never contacts a
provider, never mutates upstream data, and never raises into its caller.

CHAIN COST
----------
`get_chain` returns a whole chain, so quotes are fetched once per
(ticker, expiration, side) and indexed by strike — never once per contract.
Fetch count scales with distinct expiry/side groups, not with print count.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Dict, List, Optional, Tuple

from .flow_classifier import classify_flow_events
from .flow_clusters import build_flow_clusters
from .flow_pl import (
    DEFAULT_MARK_METHOD,
    FLOW_PL_VERSION,
    THEORETICAL_PL_LABEL,
    compute_cluster_pl,
    compute_event_pl,
    is_expired,
    years_to_expiry,
)
from . import flow_pl_store


def now_et_secs() -> Optional[int]:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
        n = _dt.datetime.now(tz)
        return n.hour * 3600 + n.minute * 60 + n.second
    except Exception:  # pragma: no cover
        return None


def session_date() -> str:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
        return _dt.datetime.now(tz).date().isoformat()
    except Exception:  # pragma: no cover
        return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


class ChainCache:
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
                    # spread_pct, liquidity_score and quote age.
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


def run_flow_pl(
    *,
    tickers: List[str],
    flow_tape_provider: Optional[Callable[[List[str], float], Dict[str, Any]]],
    chain_fetcher: Optional[Callable[[str, str, str], Any]] = None,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    method: str = DEFAULT_MARK_METHOD,
    min_premium: float = 0.0,
    default_ticker: str = "SPX",
    track: bool = True,
    attach_excursions: bool = True,
) -> Dict[str, Any]:
    """Run the whole pipeline once. Never raises.

    Args:
        track: record observations into flow_pl_store (drives MFE/MAE).
        attach_excursions: read excursions back onto the payload. The scanner
            sampler turns this off — it writes history, it does not need to read
            it back, and skipping the read keeps the cycle cheap.

    Returns a payload dict (also the /api/flow_pl body).
    """
    try:
        if flow_tape_provider is None:
            return {"available": False, "note": "No flow source wired — nothing to price.",
                    "clusters": [], "single_events": [], "count": 0,
                    "label": THEORETICAL_PL_LABEL, "flow_pl_version": FLOW_PL_VERSION}

        tape = flow_tape_provider(tickers, min_premium) or {}
        rows = tape.get("rows") or []
        if not rows:
            return {"available": True,
                    "note": tape.get("message") or "No flow rows available to price.",
                    "clusters": [], "single_events": [], "count": 0,
                    "single_event_count": 0,
                    "upstream_status": tape.get("status"),
                    "samples_recorded": 0,
                    "label": THEORETICAL_PL_LABEL, "flow_pl_version": FLOW_PL_VERSION}

        spot = None
        if last_result_provider:
            lr = last_result_provider() or {}
            ms = lr.get("market_state") or {}
            try:
                spot = float(ms.get("price")) if ms.get("price") else None
            except (TypeError, ValueError):
                spot = None

        classified = classify_flow_events(rows, spot=spot, as_of_secs=now_et_secs())
        events_by_id = {e["event_id"]: e for e in classified["events"]}
        clustered = build_flow_clusters(classified["events"])

        cache = ChainCache(chain_fetcher)
        session = session_date()
        recorded = 0
        sources: List[Dict[str, Any]] = []

        def _price(cl: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal recorded
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
                pl = compute_event_pl(ev, contract, method=method, spot=spot,
                                      t_years=years_to_expiry(exp))
                if extra:
                    pl["warnings"] = (pl.get("warnings") or []) + extra
                if track and flow_pl_store.is_ready():
                    if flow_pl_store.record_observation(
                            pl, cluster_key=ckey_s, session_date=session, spot=spot,
                            iv=(contract or {}).get("iv")):
                        recorded += 1
                members.append(pl)

            if attach_excursions and track and flow_pl_store.is_ready():
                exc = flow_pl_store.get_excursions([m["event_id"] for m in members
                                                    if m.get("event_id")])
                for m in members:
                    e = exc.get(m.get("event_id"))
                    if e:
                        m.update({k: v for k, v in e.items()
                                  if k not in ("first_seen", "last_seen")})
            priced = compute_cluster_pl(cl, members)
            # Cluster-level excursion: the label surface for Step 5 samples.
            # Recorded on the cluster's own aggregate P/L — summed member MFEs
            # would report a peak the cluster never reached.
            if track and flow_pl_store.is_ready() and priced.get("estimated_pl_dollars") is not None:
                flow_pl_store.record_cluster_observation(
                    cluster_key=ckey_s, session_date=session,
                    ticker=priced.get("ticker"),
                    pl_dollars=priced.get("estimated_pl_dollars"),
                    cost_basis=priced.get("cost_basis_dollars"))
            priced["cluster_key_string"] = ckey_s
            # The Step 3 cluster view, kept alongside the P/L view. The feature
            # writer needs the CLUSTER (end_time, aggression, print counts);
            # compute_cluster_pl deliberately returns only a P/L view and drops
            # those. Keeping them separate avoids implying the cluster's
            # descriptive stats are P/L outputs.
            src = dict(cl)
            src["cluster_key_string"] = ckey_s
            sources.append(src)
            return priced

        out_clusters = [_price(cl) for cl in clustered.get("clusters", [])]
        # Spec: P/L for qualifying individual events AND clusters. Singletons are
        # individual prints — skipping them would hide exactly the cases that
        # matter most (no quote, unknown side, far strikes).
        out_singles = [_price(cl) for cl in clustered.get("singletons", [])]

        out_clusters.sort(key=lambda c: -(abs(c.get("estimated_pl_dollars") or 0)))
        out_singles.sort(key=lambda c: -(abs(c.get("estimated_pl_dollars") or 0)))
        return {
            "available": True,
            "count": len(out_clusters),
            "clusters": out_clusters,
            "source_clusters": sources,
            "single_events": out_singles,
            "single_event_count": len(out_singles),
            "mark_method": method,
            "chain_fetches": cache.fetches,
            "chain_warnings": cache.warnings,
            "upstream_status": tape.get("status"),
            "samples_recorded": recorded,
            "label": THEORETICAL_PL_LABEL,
            "flow_pl_version": FLOW_PL_VERSION,
            "tracking": flow_pl_store.is_ready(),
        }
    except Exception as e:  # pragma: no cover
        return {"available": False, "note": f"flow P/L pipeline recovered: {e}",
                "clusters": [], "single_events": [], "count": 0, "samples_recorded": 0,
                "label": THEORETICAL_PL_LABEL, "flow_pl_version": FLOW_PL_VERSION}


def sample_flow_pl(**kwargs) -> int:
    """Scanner entry point: record one P/L observation per markable print.

    Returns the number of samples recorded. This is the whole reason MFE/MAE can
    describe the session rather than the polling pattern: without it, excursions
    only exist for the moments someone happened to have the endpoint open.

    Excursion read-back is skipped — the sampler writes history, it does not need
    to read it back, and the endpoint does that anyway.
    """
    kwargs.setdefault("track", True)
    kwargs["attach_excursions"] = False
    res = run_flow_pl(**kwargs)
    return int(res.get("samples_recorded") or 0)
