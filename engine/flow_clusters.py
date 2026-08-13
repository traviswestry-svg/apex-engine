"""engine/flow_clusters.py — APEX 9 Step 3: Flow Clustering.

Read-only consumer of **classified** flow events (`flow_classifier`), never of raw
provider rows — per spec. Aggregates related prints into auditable clusters.

WHAT A CLUSTER IS — AND IS NOT
------------------------------
A cluster is a set of prints that are *consistent with* related activity. It is
NOT proof of a single actor. The feed carries no account identity, no order id,
and no leg linkage, so two unrelated traders hitting the same contract in the
same second are indistinguishable from one trader working an order. Every
cluster therefore carries `confidence` (how well-linked the prints are) and
`intent_uncertainty` (how unclear the purpose is) — and neither ever reaches 1.0.

THE ANTI-OVER-CLUSTERING RULE
-----------------------------
Spec: "Do not force unrelated transactions into a cluster merely because they
occurred close together." Time proximity alone NEVER clusters. Prints must also
share ticker, option type, expiration, and directional interpretation, and sit
within a strike band. Opposing calls and puts, opposing directions in the same
right, and distant strikes all stay separate.

DETERMINISM (replay + recomputation)
------------------------------------
Events are de-duplicated by `event_id` and sorted by `(time, event_id)` before
chaining, so clustering is **independent of input order**. Late-arriving and
out-of-order prints produce the same clusters as if they had arrived in sequence
— recomputation over the full set is the supported model, not incremental
mutation. `cluster_id` hashes the config version + key + sorted member ids, so an
identical input always yields an identical id, and a membership change is visible
as a new id rather than a silent edit.

WHAT THIS MODULE CANNOT COMPUTE (and never fakes)
-------------------------------------------------
The spec's cluster output asks for weighted delta, weighted implied volatility,
and number of exchanges. Verified against the classified event contract: the
provider supplies **none** of these per print (`implied_volatility` and
`exchange_count` are explicitly None; there is no delta field at all). They are
emitted as None with a stated reason in `unavailable_metrics`, never modelled
here. Deriving delta would require backing IV out of a single trade print at an
unknown quote — a fabrication dressed as precision. If they become required,
enrich from `engine/options/options_data_bus.py` (which has OI/greeks) as an
explicit, stamped step.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional, Tuple

from engine.flow_authenticity import assess_cluster_authenticity

CLUSTER_VERSION = "9.3.0_FLOW_CLUSTERS"

FLOW_CLUSTERING_ENABLED = os.getenv("FLOW_CLUSTERING_ENABLED", "true").lower() == "true"

# ── Configurable clustering rules ──────────────────────────────────────────
# A change to any of these changes CLUSTER_CONFIG_VERSION, which changes every
# cluster_id — so a config change is visible in the output, never silent.
_GAP_S = float(os.getenv("FLOW_CLUSTER_GAP_S", "120"))
_STRIKE_BAND_PCT = float(os.getenv("FLOW_CLUSTER_STRIKE_BAND_PCT", "0.01"))
_MIN_PRINTS = int(os.getenv("FLOW_CLUSTER_MIN_PRINTS", "2"))
_SESSION_BOUNDARIES = os.getenv("FLOW_CLUSTER_SESSION_BOUNDARIES", "09:30,16:00")


def _config_fingerprint() -> str:
    raw = f"{CLUSTER_VERSION}|gap={_GAP_S}|band={_STRIKE_BAND_PCT}|min={_MIN_PRINTS}|" \
          f"bounds={_SESSION_BOUNDARIES}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


CLUSTER_CONFIG_VERSION = _config_fingerprint()


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _secs(time_et: Any) -> Optional[int]:
    s = str(time_et or "").strip()
    parts = s.split(":")
    if len(parts) < 2:
        return None
    try:
        h = int(parts[0]); m = int(parts[1])
        sec = int(parts[2]) if len(parts) > 2 else 0
    except (TypeError, ValueError):
        return None
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= sec < 60):
        return None
    return h * 3600 + m * 60 + sec


def _boundary_secs() -> List[int]:
    out: List[int] = []
    for tok in _SESSION_BOUNDARIES.split(","):
        s = _secs(tok.strip())
        if s is not None:
            out.append(s)
    return sorted(out)


def _crosses_session_boundary(a: int, b: int) -> bool:
    """True if a gap from a→b steps over a session boundary.

    The provider gives no date, so a cluster must not be allowed to span the
    open or the close — otherwise a 15:59 print and a 09:31 print could chain.
    """
    lo, hi = (a, b) if a <= b else (b, a)
    return any(lo < bound <= hi for bound in _boundary_secs())


def _facts(ev: Dict[str, Any]) -> Dict[str, Any]:
    return ev.get("observable_facts") or {}


def _cluster_key(ev: Dict[str, Any]) -> Optional[Tuple[Any, ...]]:
    """The hard grouping key. Prints that differ on ANY of these never cluster.

    Deliberately includes directional_bias: opposing activity in the same
    contract is opposing activity, not one campaign.
    """
    f = _facts(ev)
    tk = f.get("ticker")
    ct = (f.get("contract_type") or "").upper()
    exp = f.get("expiration")
    if not tk or ct not in ("CALL", "PUT"):
        return None
    return (tk, ct, exp or "", ev.get("directional_bias") or "UNCERTAIN")


def _in_strike_band(strike: Optional[float], lo: Optional[float],
                    hi: Optional[float]) -> bool:
    """Strike must sit within the band of the cluster's existing range."""
    if strike is None or lo is None or hi is None:
        return False
    ref = max(abs(hi), abs(strike), 1.0)
    tol = ref * _STRIKE_BAND_PCT
    return (lo - tol) <= strike <= (hi + tol)


_AGGRESSION_WEIGHT = {
    "AGGRESSIVE_BUY": 100.0, "AGGRESSIVE_SELL": 100.0,
    "BUY": 70.0, "SELL": 70.0,
    "PASSIVE_MID": 20.0, "UNKNOWN": 0.0,
}


def make_cluster_id(key: Tuple[Any, ...], member_ids: List[str]) -> str:
    """Deterministic id: config + key + sorted membership.

    Identity IS membership — a late print that changes the members yields a new
    id rather than silently redefining an existing cluster.
    """
    raw = "|".join([CLUSTER_CONFIG_VERSION, *[str(k) for k in key], *sorted(member_ids)])
    return "c_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _dedupe(events: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int, bool]:
    """Drop repeated provider messages by event_id.

    NOTE — an honest ambiguity: `event_id` hashes the print's identifying fields,
    so a genuinely distinct print with identical ticker/time/strike/price/size is
    indistinguishable from a duplicated message. We de-duplicate (the safer
    error: under-counting a repeat beats inventing volume that may not exist) and
    surface `identical_prints_collapsed` so the caller knows it happened.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    dupes = 0
    for ev in events:
        eid = ev.get("event_id")
        if not eid:
            continue
        if eid in seen:
            dupes += 1
            continue
        seen[eid] = ev
    return list(seen.values()), dupes, dupes > 0


def _summarize_members(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    prints = len(members)
    total_premium = 0.0
    total_contracts = 0.0
    px_num = 0.0
    px_den = 0.0
    strikes: List[float] = []
    times: List[int] = []
    agg_num = 0.0
    contracts_by_key: Dict[Tuple[Any, Any, Any], int] = {}
    premiums: List[float] = []
    classifications: Dict[str, int] = {}
    qualities: Dict[str, int] = {}
    intents: Dict[str, int] = {}

    for ev in members:
        f = _facts(ev)
        prem = _safe_float(f.get("premium"), 0.0) or 0.0
        qty = _safe_float(f.get("contracts"), 0.0) or 0.0
        px = _safe_float(f.get("trade_price"))
        k = _safe_float(f.get("strike"))
        t = _secs(f.get("time_et"))
        total_premium += prem
        total_contracts += qty
        premiums.append(prem)
        if px is not None and qty > 0:
            px_num += px * qty
            px_den += qty
        if k is not None:
            strikes.append(k)
        if t is not None:
            times.append(t)
        agg_num += _AGGRESSION_WEIGHT.get(ev.get("execution_aggression"), 0.0)
        ck = (f.get("contract_type"), f.get("strike"), f.get("expiration"))
        contracts_by_key[ck] = contracts_by_key.get(ck, 0) + 1
        c = ev.get("classification")
        classifications[c] = classifications.get(c, 0) + 1
        q = ev.get("data_quality")
        qualities[q] = qualities.get(q, 0) + 1
        for i in ev.get("possible_intents") or []:
            name = i.get("intent")
            intents[name] = intents.get(name, 0) + 1

    # repeat intensity: how concentrated the prints are on one contract.
    max_repeat = max(contracts_by_key.values()) if contracts_by_key else 0
    repeat_intensity = round(100.0 * max_repeat / prints, 1) if prints else 0.0
    # premium concentration: does one print dominate the cluster?
    premium_concentration = round(max(premiums) / total_premium, 3) \
        if premiums and total_premium > 0 else None

    return {
        "number_of_prints": prints,
        "total_premium": round(total_premium, 0),
        "total_contracts": int(total_contracts),
        "weighted_average_execution_price": round(px_num / px_den, 4) if px_den > 0 else None,
        "strike_range": [min(strikes), max(strikes)] if strikes else None,
        "start_time": _fmt_time(min(times)) if times else None,
        "end_time": _fmt_time(max(times)) if times else None,
        "duration_seconds": (max(times) - min(times)) if times else None,
        "aggression_score": round(agg_num / prints, 1) if prints else 0.0,
        "repeat_intensity_score": repeat_intensity,
        "distinct_contracts": len(contracts_by_key),
        "premium_concentration": premium_concentration,
        "classification_summary": classifications,
        "data_quality_summary": qualities,
        "intent_summary": intents,
    }


def _fmt_time(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _cluster_confidence(stats: Dict[str, Any], members: List[Dict[str, Any]]) -> float:
    """How well-linked are these prints? NOT how good the trade is.

    Caps below 1.0 by construction: without account identity, linkage is always
    inference. More prints, tighter timing, and repeated hits on one contract all
    raise it; degraded data lowers it.
    """
    prints = stats["number_of_prints"]
    score = 0.30
    if prints >= 5:
        score += 0.20
    elif prints >= 3:
        score += 0.12
    else:
        score += 0.05
    dur = stats.get("duration_seconds")
    if dur is not None:
        if dur <= 5:
            score += 0.18
        elif dur <= 30:
            score += 0.10
        elif dur <= 120:
            score += 0.04
    if stats["repeat_intensity_score"] >= 80:
        score += 0.12
    elif stats["repeat_intensity_score"] >= 50:
        score += 0.06
    degraded = stats["data_quality_summary"].get("DEGRADED", 0)
    if degraded:
        score -= 0.15 * (degraded / max(prints, 1))
    if stats["aggression_score"] >= 90:
        score += 0.05
    return round(max(0.05, min(0.85, score)), 2)


def _intent_uncertainty(members: List[Dict[str, Any]], stats: Dict[str, Any]) -> Dict[str, Any]:
    """How unclear is the purpose? Reported, never resolved away."""
    prints = max(len(members), 1)
    uncertain_flags = stats["intent_summary"].get("directional_interpretation_uncertain", 0)
    spread_legs = stats["intent_summary"].get("spread_leg_candidate", 0)
    rolls = stats["intent_summary"].get("likely_roll", 0)
    hedges = stats["intent_summary"].get("possible_hedge", 0)
    mean_dir_conf = sum(_safe_float(e.get("directional_confidence"), 0.0) or 0.0
                        for e in members) / prints
    score = round(min(1.0, (uncertain_flags / prints) * 0.5 +
                      (spread_legs / prints) * 0.3 +
                      (1.0 - mean_dir_conf) * 0.4), 2)
    notes: List[str] = []
    if spread_legs:
        notes.append(f"{spread_legs}/{prints} prints look like spread legs — the cluster's "
                     f"directional reading may be an artefact of one leg of a package.")
    if rolls:
        notes.append(f"{rolls}/{prints} prints pair with another expiration — some of this "
                     f"cluster may be a roll rather than new exposure.")
    if hedges:
        notes.append(f"{hedges}/{prints} prints are consistent with hedging as well as "
                     f"direction; the two are indistinguishable on the tape.")
    if uncertain_flags:
        notes.append(f"{uncertain_flags}/{prints} prints have no observable initiating side.")
    return {"score": score, "notes": notes}


def _build_cluster(key: Tuple[Any, ...], members: List[Dict[str, Any]]) -> Dict[str, Any]:
    member_ids = [m.get("event_id") for m in members if m.get("event_id")]
    stats = _summarize_members(members)
    warnings: List[str] = []

    tk, ct, exp, direction = key
    if not exp:
        warnings.append("Members have no expiration — contract identity incomplete.")
    if stats["data_quality_summary"].get("DEGRADED"):
        warnings.append(f"{stats['data_quality_summary']['DEGRADED']} member print(s) are "
                        f"DEGRADED; cluster metrics are correspondingly weaker.")
    if stats.get("premium_concentration") is not None and stats["premium_concentration"] > 0.8:
        warnings.append(f"One print carries {stats['premium_concentration']:.0%} of cluster "
                        f"premium — this is closer to a single trade than a campaign.")
    warnings.append("Cluster membership is inferred from observable print attributes. The feed "
                    "carries no account identity, so these prints cannot be proven to share an "
                    "originator.")

    cluster = {
        "cluster_id": make_cluster_id(key, member_ids),
        "cluster_key": {"ticker": tk, "option_type": ct, "expiration": exp,
                        "directional_interpretation": direction},
        "member_event_ids": sorted(member_ids),
        "ticker": tk,
        "option_type": ct,
        "expiration": exp or None,
        "directional_interpretation": direction,
        **stats,
        "confidence": _cluster_confidence(stats, members),
        "intent_uncertainty": _intent_uncertainty(members, stats),
        # Required by spec but NOT derivable from the provider's per-print data.
        # Emitted explicitly as unavailable rather than modelled into false precision.
        "weighted_delta": None,
        "weighted_implied_volatility": None,
        "number_of_exchanges": None,
        "unavailable_metrics": {
            "weighted_delta": "No delta on the print, and no IV to derive one; modelling it "
                              "from a single trade price at an unknown quote would be false "
                              "precision.",
            "weighted_implied_volatility": "Provider supplies no per-print implied volatility.",
            "number_of_exchanges": "Provider supplies no exchange field; a SWEEP is taken as "
                                   "provider-reported rather than counted across venues.",
        },
        "warnings": warnings,
        "cluster_version": CLUSTER_VERSION,
        "cluster_config_version": CLUSTER_CONFIG_VERSION,
        "classifier_versions": sorted({m.get("classifier_version") for m in members
                                       if m.get("classifier_version")}),
    }
    cluster["flow_authenticity"] = assess_cluster_authenticity(cluster)
    cluster["directional_confidence_adjusted"] = round(
        cluster["confidence"] * cluster["flow_authenticity"]["directional_confidence_multiplier"], 3
    )
    if cluster["flow_authenticity"]["scheduled_candidate"]:
        cluster["warnings"].append(
            "Clock-synchronised complex activity is labelled SCHEDULED/AUTOMATED FLOW "
            "until persistence, price, ES, and liquidity response confirm direction."
        )
    return cluster


def build_flow_clusters(events: List[Dict[str, Any]], *,
                        min_prints: Optional[int] = None) -> Dict[str, Any]:
    """Cluster classified flow events. Read-only; never mutates inputs; never raises.

    Args:
        events: output of `flow_classifier.classify_flow_events(...)["events"]`.
        min_prints: clusters smaller than this are reported as singletons instead
            (they are still returned, so no print is ever lost).
    """
    try:
        if not FLOW_CLUSTERING_ENABLED:
            return {"available": False, "note": "Flow clustering disabled "
                                                "(FLOW_CLUSTERING_ENABLED=false).",
                    "clusters": [], "singletons": [], "count": 0,
                    "cluster_version": CLUSTER_VERSION,
                    "cluster_config_version": CLUSTER_CONFIG_VERSION}
        floor = _MIN_PRINTS if min_prints is None else int(min_prints)
        if not events:
            return {"available": True, "count": 0, "clusters": [], "singletons": [],
                    "unclusterable": [], "duplicates_dropped": 0,
                    "summary": _cluster_summary([]),
                    "cluster_version": CLUSTER_VERSION,
                    "cluster_config_version": CLUSTER_CONFIG_VERSION}

        deduped, dupes, collapsed = _dedupe(events)

        # Deterministic ordering — this is what makes late/out-of-order prints
        # produce identical clusters to in-order arrival.
        def _sort_key(ev):
            t = _secs(_facts(ev).get("time_et"))
            return (t if t is not None else 10 ** 9, str(ev.get("event_id") or ""))
        ordered = sorted(deduped, key=_sort_key)

        groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
        unclusterable: List[Dict[str, Any]] = []
        for ev in ordered:
            key = _cluster_key(ev)
            t = _secs(_facts(ev).get("time_et"))
            # A malformed print (classifier returned AMBIGUOUS *and* DEGRADED —
            # e.g. zero contracts / zero premium) carries no usable activity.
            # Clustering it would manufacture a one-print "cluster" out of
            # garbage, so it is retained here instead of being dressed up.
            malformed = (ev.get("classification") == "AMBIGUOUS"
                         and ev.get("data_quality") == "DEGRADED")
            if key is None or t is None or malformed:
                if malformed:
                    reason = ("Print is malformed (no usable volume/premium); retained but not "
                              "clustered — it evidences no activity to relate.")
                else:
                    reason = "Malformed or untimed print — cannot be positioned in a cluster."
                unclusterable.append({"event_id": ev.get("event_id"), "reason": reason})
                continue
            groups.setdefault(key, []).append(ev)

        clusters: List[Dict[str, Any]] = []
        singletons: List[Dict[str, Any]] = []
        for key, members in groups.items():
            for chain in _chain(members):
                built = _build_cluster(key, chain)
                if built["number_of_prints"] >= floor:
                    clusters.append(built)
                else:
                    singletons.append(built)

        clusters.sort(key=lambda c: (-(c.get("total_premium") or 0), c["cluster_id"]))
        singletons.sort(key=lambda c: (-(c.get("total_premium") or 0), c["cluster_id"]))

        out = {
            "available": True,
            "count": len(clusters),
            "clusters": clusters,
            "singletons": singletons,
            "unclusterable": unclusterable,
            "duplicates_dropped": dupes,
            "summary": _cluster_summary(clusters),
            "cluster_version": CLUSTER_VERSION,
            "cluster_config_version": CLUSTER_CONFIG_VERSION,
            "config": {"gap_seconds": _GAP_S, "strike_band_pct": _STRIKE_BAND_PCT,
                       "min_prints": floor, "session_boundaries": _SESSION_BOUNDARIES},
        }
        if collapsed:
            out["identical_prints_collapsed"] = dupes
            out["duplicate_note"] = (
                f"{dupes} print(s) shared an identical fingerprint and were treated as "
                f"duplicate provider messages. Genuinely distinct prints with identical "
                f"ticker/time/strike/price/size are indistinguishable from duplicates in "
                f"this feed; volume may be understated rather than invented.")
        return out
    except Exception as e:  # pragma: no cover - clustering must never break the tape
        return {"available": False, "note": f"clustering recovered from error: {e}",
                "clusters": [], "singletons": [], "count": 0,
                "cluster_version": CLUSTER_VERSION,
                "cluster_config_version": CLUSTER_CONFIG_VERSION}


def _strike_bands(members: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Split a key group into strike bands BEFORE time-chaining.

    Why this exists: a purely sequential time chain is broken by any out-of-band
    print that happens to land between two related prints. A 6900 print arriving
    between two 6300 sweeps would end the 6300 chain and start a new one, tearing
    one campaign into two — an artefact of arrival interleaving, not of the market.

    Banding uses complete linkage (a strike joins only if the band's WHOLE span
    stays inside tolerance), which also prevents single-linkage drift, where
    6300~6360~6420 would daisy-chain into one implausibly wide cluster.
    """
    bands: List[Dict[str, Any]] = []
    # Sort by strike (then event_id) so banding is deterministic.
    for ev in sorted(members, key=lambda e: (_safe_float(_facts(e).get("strike"), 0.0) or 0.0,
                                             str(e.get("event_id") or ""))):
        k = _safe_float(_facts(ev).get("strike"))
        if k is None:
            # No strike: cannot be banded — keep it isolated rather than guess.
            bands.append({"lo": None, "hi": None, "members": [ev]})
            continue
        placed = False
        for b in bands:
            if b["lo"] is None:
                continue
            new_lo, new_hi = min(b["lo"], k), max(b["hi"], k)
            ref = max(abs(new_hi), 1.0)
            if (new_hi - new_lo) <= ref * _STRIKE_BAND_PCT:
                b["members"].append(ev)
                b["lo"], b["hi"] = new_lo, new_hi
                placed = True
                break
        if not placed:
            bands.append({"lo": k, "hi": k, "members": [ev]})
    return [b["members"] for b in bands]


def _chain(members: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Split a same-key group into strike-banded, time-contiguous chains.

    Strike banding happens first (see _strike_bands) so that interleaved,
    unrelated strikes cannot tear a campaign apart. Within a band, a print joins
    the current chain only if it is inside the gap window and does not step over
    a session boundary. Otherwise a new chain starts — this is the split
    behaviour, and its inverse (a late print bridging two chains) is how a merge
    occurs on recomputation.
    """
    chains: List[List[Dict[str, Any]]] = []
    for band in _strike_bands(members):
        ordered = sorted(band, key=lambda e: (_secs(_facts(e).get("time_et")) or 0,
                                              str(e.get("event_id") or "")))
        current: List[Dict[str, Any]] = []
        last_t: Optional[int] = None
        for ev in ordered:
            t = _secs(_facts(ev).get("time_et"))
            if not current:
                current = [ev]
                last_t = t
                continue
            gap_ok = last_t is not None and t is not None and (t - last_t) <= _GAP_S
            boundary = _crosses_session_boundary(last_t, t) \
                if (last_t is not None and t is not None) else False
            if gap_ok and not boundary:
                current.append(ev)
                last_t = t
            else:
                chains.append(current)
                current = [ev]
                last_t = t
        if current:
            chains.append(current)
    return chains


def _cluster_summary(clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_dir: Dict[str, int] = {}
    prem_by_dir: Dict[str, float] = {}
    for c in clusters:
        d = c.get("directional_interpretation") or "UNCERTAIN"
        by_dir[d] = by_dir.get(d, 0) + 1
        prem_by_dir[d] = prem_by_dir.get(d, 0.0) + (c.get("total_premium") or 0.0)
    return {
        "cluster_count": len(clusters),
        "by_directional_interpretation": by_dir,
        "premium_by_directional_interpretation": {k: round(v, 0) for k, v in prem_by_dir.items()},
        "note": ("Clusters group prints that are consistent with related activity. They are not "
                 "proof of a single participant, and premium totals are not positioning."),
    }


def compare_classifier_versions(events_a: List[Dict[str, Any]],
                                events_b: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare clusterings from two classifier versions over the same prints.

    Supports the spec's "comparison between classifier versions": if a classifier
    change silently reshapes clusters, this makes it visible rather than
    discovered later in a backtest.
    """
    a = build_flow_clusters(events_a)
    b = build_flow_clusters(events_b)
    ids_a = {c["cluster_id"] for c in a.get("clusters", [])}
    ids_b = {c["cluster_id"] for c in b.get("clusters", [])}
    return {
        "a": {"versions": sorted({e.get("classifier_version") for e in events_a if e.get("classifier_version")}),
              "cluster_count": a.get("count"), "config": a.get("cluster_config_version")},
        "b": {"versions": sorted({e.get("classifier_version") for e in events_b if e.get("classifier_version")}),
              "cluster_count": b.get("count"), "config": b.get("cluster_config_version")},
        "identical": ids_a == ids_b,
        "only_in_a": sorted(ids_a - ids_b),
        "only_in_b": sorted(ids_b - ids_a),
        "shared": sorted(ids_a & ids_b),
    }


def health() -> Dict[str, Any]:
    return {
        "enabled": FLOW_CLUSTERING_ENABLED,
        "cluster_version": CLUSTER_VERSION,
        "cluster_config_version": CLUSTER_CONFIG_VERSION,
        "config": {
            "gap_seconds": _GAP_S,
            "strike_band_pct": _STRIKE_BAND_PCT,
            "min_prints": _MIN_PRINTS,
            "session_boundaries": _SESSION_BOUNDARIES,
        },
        "key_dimensions": ["ticker", "option_type", "expiration",
                           "directional_interpretation", "strike_band", "timestamp_proximity"],
        "unavailable_metrics": ["weighted_delta", "weighted_implied_volatility",
                                "number_of_exchanges"],
        "determinism": "Events are de-duplicated by event_id and sorted by (time, event_id) "
                       "before chaining, so clustering is independent of arrival order.",
    }
