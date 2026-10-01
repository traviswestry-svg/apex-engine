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
                    "clusters": [], "source_clusters": [], "single_events": [], "count": 0,
                    "source_diagnostics": {"raw_rows": 0, "normalized_rows": 0,
                                           "classified_events": 0, "clusters": 0,
                                           "singletons": 0, "unclusterable": 0,
                                           "reason": "NO_FLOW_SOURCE"},
                    "label": THEORETICAL_PL_LABEL, "flow_pl_version": FLOW_PL_VERSION}

        tape = flow_tape_provider(tickers, min_premium) or {}
        rows = tape.get("rows") or []
        if not rows:
            nd = tape.get("normalization_diagnostics") or {}
            return {"available": True,
                    "note": tape.get("message") or "No flow rows available to price.",
                    "clusters": [], "source_clusters": [], "single_events": [], "count": 0,
                    "single_event_count": 0,
                    "upstream_status": tape.get("status"),
                    "samples_recorded": 0,
                    "source_diagnostics": {
                        "raw_rows": int(nd.get("raw_rows") or 0),
                        "normalized_rows": int(nd.get("normalized_rows") or 0),
                        "classified_events": 0, "clusters": 0, "singletons": 0,
                        "unclusterable": 0,
                        "invalid_trade_time": int(nd.get("invalid_trade_time") or 0),
                        "reason": "NO_NORMALIZED_FLOW_ROWS",
                    },
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
        nd = tape.get("normalization_diagnostics") or {}
        source_diagnostics = {
            "raw_rows": int(nd.get("raw_rows") or len(rows)),
            "normalized_rows": len(rows),
            "classified_events": len(classified.get("events") or []),
            "clusters": len(clustered.get("clusters") or []),
            "singletons": len(clustered.get("singletons") or []),
            "unclusterable": len(clustered.get("unclusterable") or []),
            "duplicates_dropped": int(clustered.get("duplicates_dropped") or 0),
            "invalid_trade_time": int(nd.get("invalid_trade_time") or 0),
            "classifier_quality": classified.get("summary", {}).get("by_data_quality", {}),
        }
        if source_diagnostics["clusters"] or source_diagnostics["singletons"]:
            source_diagnostics["reason"] = "SOURCE_CLUSTERS_AVAILABLE"
        elif source_diagnostics["unclusterable"]:
            source_diagnostics["reason"] = "ALL_CLASSIFIED_EVENTS_UNCLUSTERABLE"
        elif source_diagnostics["classified_events"]:
            source_diagnostics["reason"] = "CLASSIFIED_WITHOUT_CLUSTER_OUTPUT"
        else:
            source_diagnostics["reason"] = "NO_CLASSIFIED_EVENTS"

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
                # APEX 69.10.24: ownership comes from immutable origin bindings
                # published by the successful feature persistence/registration boundary.
                # The current cluster tuple is observational and may evolve; it is never
                # used to manufacture canonical ownership.
                decision_time = f"{session}T{cl.get('end_time')}" if cl.get("end_time") else None
                # APEX 69.10.25: preserve deterministic event ancestry even when a
                # rebuilt cluster gains new unbound members. A partial transport is
                # authorized only when every bound member names the same immutable
                # persisted origin. Conflicting bound origins fail closed.
                transport = flow_pl_store.resolve_feature_origin_transport(
                    event_ids=list(cl.get("member_event_ids") or []))
                origin = transport.get("origin") if transport.get("owner_authorized") else None
                owner_validated = bool(origin and flow_pl_store.verify_sample_identity_owner(
                    sample_id=origin.get("sample_id") or "",
                    session_date=origin.get("session_date") or "",
                    legacy_cluster_key=origin.get("legacy_cluster_key") or "",
                    decision_time=origin.get("decision_time") or ""))

                # Preserve 69.10.23 exact-current-tuple telemetry as a fallback
                # diagnostic only. It never gains write authority.
                identity = (flow_pl_store.resolve_exact_sample_identity(
                    session_date=session, legacy_cluster_key=ckey_s,
                    decision_time=decision_time) if decision_time else None)
                if decision_time:
                    flow_pl_store.record_feature_pl_handoff_observation(
                        session_date=session, legacy_cluster_key=ckey_s,
                        decision_time=decision_time,
                        exact_owner_sample_id=(identity or {}).get("sample_id"))

                cap = None
                transport_status = str(transport.get("transport_status") or "UNKNOWN")
                reason = (f"ORIGIN_TRANSPORT_{transport_status}" if not origin else
                          ("ORIGIN_OWNER_VALIDATED" if owner_validated
                           else "ORIGIN_OWNER_VALIDATION_FAILED"))
                if origin and owner_validated:
                    cap = flow_pl_store.record_sample_excursion(
                        sample_id=origin["sample_id"], session_date=origin["session_date"],
                        ticker=priced.get("ticker"),
                        pl_dollars=priced.get("estimated_pl_dollars"),
                        cost_basis=priced.get("cost_basis_dollars"),
                        decision_time=origin["decision_time"],
                        legacy_cluster_key=origin["legacy_cluster_key"],
                        require_registered_owner=True)
                    if cap:
                        flow_pl_store.record_sample_pl_lifecycle(
                            sample_id=origin["sample_id"], session_date=origin["session_date"],
                            legacy_cluster_key=origin["legacy_cluster_key"],
                            decision_time=origin["decision_time"],
                            state=("PL_OBSERVED_EXCURSION_WRITTEN" if cap.get("first_sample")
                                   else "PL_OBSERVED_EXCURSION_UPDATED"),
                            reason="LATER_ORIGIN_PROVENANCE_REAL_PL", pl_observed=True,
                            excursion_written=True)
                if decision_time:
                    flow_pl_store.record_feature_origin_transport_observation(
                        observation_session_date=session,
                        observation_legacy_cluster_key=ckey_s,
                        observation_decision_time=decision_time, transport=transport)
                    flow_pl_store.record_feature_origin_pl_observation(
                        observation_session_date=session,
                        observation_legacy_cluster_key=ckey_s,
                        observation_decision_time=decision_time, origin=origin,
                        owner_validated=owner_validated, diagnostic_reason=reason,
                        excursion_written=bool(cap and cap.get("first_sample")),
                        excursion_updated=bool(cap and not cap.get("first_sample")))
            priced["cluster_key_string"] = ckey_s
            # The Step 3 cluster view, kept alongside the P/L view. The feature
            # writer needs the CLUSTER (end_time, aggression, print counts);
            # compute_cluster_pl deliberately returns only a P/L view and drops
            # those. Keeping them separate avoids implying the cluster's
            # descriptive stats are P/L outputs.
            src = dict(cl)
            src["cluster_key_string"] = ckey_s
            # Private writer handoff, never a model feature. The feature writer
            # records this aggregate P/L under the immutable sample_id only once
            # the cluster is sealed.
            src["_excursion_observation"] = {
                "pl_dollars": priced.get("estimated_pl_dollars"),
                "cost_basis": priced.get("cost_basis_dollars"),
                "ticker": priced.get("ticker") or ckey.get("ticker"),
                "legacy_cluster_key": ckey_s,
            }

            # APEX 69.10.5: this source-stage pipeline MUST NOT attempt canonical
            # sample excursion capture. At this point the cluster may not be sealed,
            # may fail the replay-frame freshness guard, or may never become an
            # immutable feature sample. Counting that ordinary pre-persistence state
            # as ``missing_feature_sample`` created thousands of false capture
            # failures and could also resolve a coarse legacy key to the wrong sealed
            # incarnation. The feature writer is the sole production capture owner:
            # it first confirms the exact feature ``sample_id`` exists, registers the
            # identity bridge, and only then records a real P/L mark. No identity is
            # reconstructed here and no missing canonical sample is treated as an
            # attempted capture.
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
            "source_diagnostics": source_diagnostics,
        }
    except Exception as e:  # pragma: no cover
        return {"available": False, "note": f"flow P/L pipeline recovered: {e}",
                "clusters": [], "source_clusters": [], "single_events": [], "count": 0,
                "samples_recorded": 0,
                "source_diagnostics": {"reason": "PIPELINE_ERROR", "error_type": type(e).__name__},
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


def reobserve_bound_feature_origins(*, session_date_value: str,
        chain_fetcher: Optional[Callable[[str, str, str], Any]],
        last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        method: str = DEFAULT_MARK_METHOD) -> Dict[str, int]:
    """Reprice exact persisted origins from durable event bindings.

    This is APEX 69.10.27's post-persistence continuation path. It never searches
    for an owner. The binding table supplies the canonical owner and the tracking
    table supplies only facts previously observed for that exact event. Current
    option-chain quotes provide the genuine later mark. Missing quotes fail closed.
    """
    report = {"candidates": 0, "samples_seen": 0, "samples_marked": 0,
              "excursions_inserted": 0, "excursions_updated": 0,
              "unmarkable": 0, "owner_validation_failed": 0, "errors": 0}
    try:
        rows = flow_pl_store.get_bound_origin_repricing_candidates(session_date_value)
        report["candidates"] = len(rows)
        if not rows or not chain_fetcher:
            return report
        spot = None
        if last_result_provider:
            lr = last_result_provider() or {}
            ms = lr.get("market_state") or {}
            try:
                spot = float(ms.get("price")) if ms.get("price") else None
            except (TypeError, ValueError):
                spot = None
        cache = ChainCache(chain_fetcher)
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["sample_id"]), []).append(row)
        report["samples_seen"] = len(grouped)
        for sample_id, members in grouped.items():
            owner = members[0]
            if not flow_pl_store.verify_sample_identity_owner(
                    sample_id=sample_id, session_date=owner["session_date"],
                    legacy_cluster_key=owner["legacy_cluster_key"],
                    decision_time=owner["decision_time"]):
                report["owner_validation_failed"] += 1
                continue
            pls: List[Dict[str, Any]] = []
            for r in members:
                contract = cache.contract(r.get("ticker") or "SPX", r.get("expiration") or "",
                                          (r.get("contract_type") or "").upper(), r.get("strike"))
                agg = "AGGRESSIVE_BUY" if r.get("position_side") == "LONG" else (
                      "AGGRESSIVE_SELL" if r.get("position_side") == "SHORT" else "UNKNOWN")
                qty = int(r.get("contracts") or 0)
                entry = r.get("entry_mark")
                mult = float(r.get("multiplier") or 100.0)
                event = {"event_id": r.get("event_id"), "execution_aggression": agg,
                         "observable_facts": {"ticker": r.get("ticker"),
                         "time_et": r.get("entry_time_et"), "contract_type": r.get("contract_type"),
                         "strike": r.get("strike"), "expiration": r.get("expiration"),
                         "trade_price": entry, "contracts": qty,
                         "premium": (float(entry) * qty * mult if entry is not None and qty else None)}}
                pl = compute_event_pl(event, contract, method=method, spot=spot,
                                      entry_spot=r.get("entry_spot"), entry_iv=r.get("entry_iv"),
                                      t_years=years_to_expiry(r.get("expiration")))
                if pl.get("markable") and pl.get("estimated_pl_dollars") is not None:
                    pls.append(pl)
            if not pls:
                report["unmarkable"] += 1
                continue
            total_pl = round(sum(float(x["estimated_pl_dollars"]) for x in pls), 2)
            cost = round(sum(float(x.get("entry_mark") or 0) * int(x.get("contracts") or 0) *
                             float(x.get("multiplier") or 100.0) for x in pls), 2)
            cap = flow_pl_store.record_sample_excursion(
                sample_id=sample_id, session_date=owner["session_date"],
                ticker=owner.get("ticker") or "SPX", pl_dollars=total_pl, cost_basis=cost,
                decision_time=owner["decision_time"],
                legacy_cluster_key=owner["legacy_cluster_key"], require_registered_owner=True)
            if not cap:
                report["errors"] += 1
                continue
            report["samples_marked"] += 1
            first = bool(cap.get("first_sample"))
            report["excursions_inserted" if first else "excursions_updated"] += 1
            flow_pl_store.record_sample_pl_lifecycle(
                sample_id=sample_id, session_date=owner["session_date"],
                legacy_cluster_key=owner["legacy_cluster_key"], decision_time=owner["decision_time"],
                state=("PL_OBSERVED_EXCURSION_WRITTEN" if first else "PL_OBSERVED_EXCURSION_UPDATED"),
                reason="DURABLE_BOUND_ORIGIN_REAL_PL", pl_observed=True, excursion_written=True)
        return report
    except Exception:
        report["errors"] += 1
        return report


def capture_persisted_feature_excursions(targets: List[Dict[str, Any]]) -> Dict[str, int]:
    """Capture real live P/L marks for canonical feature identities after persistence.

    APEX 69.4.3 production boundary: scanner feature persistence happens before this
    function is invoked. ``targets`` are emitted by the feature writer only for
    sealed samples whose immutable feature row exists and whose exact sample_id was
    registered. No identity is reconstructed and no missing P/L is synthesized.
    """
    report = {"attempted": 0, "inserted": 0, "updated": 0,
              "missing_pl": 0, "errors": 0, "store_ready": 0}
    try:
        if not flow_pl_store.is_ready():
            flow_pl_store.init_db()
        report["store_ready"] = 1 if flow_pl_store.is_ready() else 0
        if not flow_pl_store.is_ready():
            return report
        for target in targets or []:
            sid = target.get("sample_id")
            if not sid:
                continue
            report["attempted"] += 1
            if target.get("pl_dollars") is None:
                report["missing_pl"] += 1
                flow_pl_store.record_capture_audit(
                    attempted=1, missing_pl=1, sample_id=sid, canonical_attempted=1)
                flow_pl_store.record_sample_pl_lifecycle(
                    sample_id=sid, session_date=target.get("session_date"),
                    legacy_cluster_key=target.get("legacy_cluster_key"),
                    decision_time=target.get("decision_time"), state="AWAITING_REAL_PL",
                    reason="DEFERRED_CAPTURE_HAS_NO_REAL_PL")
                continue
            cap = flow_pl_store.record_sample_excursion(
                sample_id=sid,
                session_date=target.get("session_date"),
                ticker=target.get("ticker"),
                pl_dollars=target.get("pl_dollars"),
                cost_basis=target.get("cost_basis"),
                decision_time=target.get("decision_time"),
                legacy_cluster_key=target.get("legacy_cluster_key"),
                require_registered_owner=True,
            )
            if cap:
                if cap.get("first_sample"):
                    report["inserted"] += 1
                    _state = "PL_OBSERVED_EXCURSION_WRITTEN"
                else:
                    report["updated"] += 1
                    _state = "PL_OBSERVED_EXCURSION_UPDATED"
                flow_pl_store.record_sample_pl_lifecycle(
                    sample_id=sid, session_date=target.get("session_date"),
                    legacy_cluster_key=target.get("legacy_cluster_key"),
                    decision_time=target.get("decision_time"), state=_state,
                    reason="DEFERRED_EXACT_SAMPLE_REAL_PL", pl_observed=True,
                    excursion_written=True)
            else:
                report["errors"] += 1
        return report
    except Exception:
        report["errors"] += 1
        return report
