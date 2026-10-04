"""APEX 69.10.30 — Canonical Abstention Causality & Opportunity Recovery Intelligence.

Read-only/advisory analysis over immutable decision-effectiveness attribution rows.
It collapses mirrored decision-object paths into canonical evidence families,
distinguishes explicit authoritative blockers from non-authoritative contributors,
and clusters repeated missed-opportunity observations from the same market move.

This module never changes decisions, thresholds, calibration, learning eligibility,
position sizing, broker state, or execution authority.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from .decision_outcome_attribution import DEFAULT_DB, _availability, _open_read

VERSION = "69.10.30"
SCHEMA_VERSION = "apex.abstention_causality.v1"

# These states are decision-time evidence of friction/absence/conflict.  They are
# contributors only unless the frozen gate explicitly carried blocked=true.
_CONTRIBUTOR_STATES = {
    "ABSTAIN", "BLOCK", "BLOCKED", "DATA_LIMITED", "FAIL", "FAILED",
    "INELIGIBLE", "NO_FLOW", "NO_TRADE", "PREPARING", "STAND_DOWN",
    "SUPPRESS", "TIMEFRAME_CONFLICT", "UNAVAILABLE", "WATCH_ONLY",
}


def _u(value: Any) -> str:
    return str(value or "").strip().upper()


def canonical_family(path: str) -> str:
    """Collapse mirrored JSON paths into stable semantic evidence families."""
    p = str(path or "").lower()
    if "decision_state" in p or p.endswith(".acceptance.state") or p == "acceptance.state":
        return "DECISION_AUTHORITY"
    if "evidence_eligibility" in p:
        return "EVIDENCE_ELIGIBILITY"
    if "flow_excitation" in p or "flow_surprise" in p:
        return "FLOW"
    if "gamma" in p:
        return "GAMMA"
    if "auction_state" in p:
        return "AUCTION"
    if "institutional_intent" in p or "sweep_detection" in p:
        return "INSTITUTIONAL_INTENT"
    if "residual_pressure" in p:
        return "RESIDUAL_PRESSURE"
    if "multi_horizon" in p or "horizons." in p or "timeframe" in p:
        return "MULTI_HORIZON_TRANSITION"
    if "dynamic_state" in p:
        return "DYNAMIC_STATE"
    if "consensus" in p:
        return "CONSENSUS"
    if "conviction" in p:
        return "CONVICTION"
    if "reasoning_graph" in p or "evidence_graph" in p or "engine_opinions" in p:
        return "REASONING_GRAPH"
    return "OTHER"


def _parse_json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _canonicalize_gates(gates: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    families: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "authoritative_block": False,
        "explicit_block_paths": [],
        "contributor_states": Counter(),
        "contributor_paths": [],
        "observations": 0,
    })
    explicit_block_paths = []
    for raw in gates or []:
        if not isinstance(raw, Mapping):
            continue
        path = str(raw.get("gate") or "UNKNOWN")
        state = _u(raw.get("state")) or "UNKNOWN"
        blocked = bool(raw.get("blocked"))
        family = canonical_family(path)
        f = families[family]
        f["observations"] += 1
        if blocked:
            f["authoritative_block"] = True
            if path not in f["explicit_block_paths"]:
                f["explicit_block_paths"].append(path)
            explicit_block_paths.append(path)
        if blocked or state in _CONTRIBUTOR_STATES:
            f["contributor_states"][state] += 1
            if path not in f["contributor_paths"] and len(f["contributor_paths"]) < 12:
                f["contributor_paths"].append(path)
    out = {}
    for family, f in sorted(families.items()):
        if not f["authoritative_block"] and not f["contributor_states"]:
            continue
        out[family] = {
            "authoritative_block": bool(f["authoritative_block"]),
            "explicit_block_paths": sorted(f["explicit_block_paths"]),
            "contributor_states": dict(sorted(f["contributor_states"].items())),
            "contributor_paths": sorted(f["contributor_paths"]),
            "observations": int(f["observations"]),
        }
    return {
        "families": out,
        "explicit_block_paths": sorted(set(explicit_block_paths)),
        "causal_resolution": "EXPLICIT_BLOCKER" if explicit_block_paths else "CONTRIBUTORS_ONLY",
    }


def _rows(path: str | Path = DEFAULT_DB) -> list[Dict[str, Any]]:
    availability = _availability(path)
    if availability.get("status") != "READY":
        return []
    with _open_read(path) as conn:
        rows = conn.execute(
            """SELECT decision_id,captured_at,ticker,action,direction,confidence,horizon_seconds,
                      directional_move,mfe,mae,missed_opportunity,protective_abstention,gates_json,outcome_json
               FROM decision_effectiveness_attribution
               WHERE action_class='ABSTAIN' AND status='GRADED'
               ORDER BY captured_at ASC"""
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["gates"] = _parse_json(item.pop("gates_json", None), [])
        item["outcome"] = _parse_json(item.pop("outcome_json", None), {})
        item["causality"] = _canonicalize_gates(item["gates"])
        out.append(item)
    return out


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _cluster_id(ticker: str, direction: str, anchor_at: str) -> str:
    raw = f"{ticker}|{direction}|{anchor_at}".encode("utf-8")
    return "aoc_" + hashlib.sha256(raw).hexdigest()[:20]


def opportunity_clusters(path: str | Path = DEFAULT_DB) -> list[Dict[str, Any]]:
    """Cluster repeated missed observations using the frozen grading horizon.

    A member joins a cluster only when ticker+direction match and its capture time
    is within the anchor member's horizon.  This prevents every scanner tick from
    being treated as an independent opportunity while avoiding chain-merging.
    """
    missed = [r for r in _rows(path) if bool(r.get("missed_opportunity"))]
    clusters: list[Dict[str, Any]] = []
    active: Dict[tuple[str, str], Dict[str, Any]] = {}
    for r in missed:
        key = (str(r.get("ticker") or ""), _u(r.get("direction")))
        when = _dt(str(r["captured_at"]))
        current = active.get(key)
        horizon = int(r.get("horizon_seconds") or 300)
        if current is None or (when - current["_anchor_dt"]).total_seconds() > int(current["horizon_seconds"]):
            current = {
                "cluster_id": _cluster_id(key[0], key[1], str(r["captured_at"])),
                "ticker": key[0], "direction": key[1], "anchor_at": str(r["captured_at"]),
                "last_at": str(r["captured_at"]), "horizon_seconds": horizon,
                "decision_ids": [], "observations": 0, "max_mfe": None, "worst_mae": None,
                "max_directional_move": None, "confidence_sum": 0.0,
                "canonical_families": Counter(), "authoritative_families": Counter(),
                "_anchor_dt": when,
            }
            active[key] = current
            clusters.append(current)
        current["last_at"] = str(r["captured_at"])
        current["decision_ids"].append(str(r["decision_id"]))
        current["observations"] += 1
        current["confidence_sum"] += float(r.get("confidence") or 0.0)
        for metric, mode in (("mfe", "max"), ("directional_move", "max"), ("mae", "min")):
            value = r.get(metric)
            if value is None:
                continue
            keyname = {"mfe": "max_mfe", "directional_move": "max_directional_move", "mae": "worst_mae"}[metric]
            old = current[keyname]
            current[keyname] = float(value) if old is None else (max(old, float(value)) if mode == "max" else min(old, float(value)))
        for family, detail in r["causality"]["families"].items():
            current["canonical_families"][family] += 1
            if detail.get("authoritative_block"):
                current["authoritative_families"][family] += 1
    result = []
    for c in clusters:
        item = {k: v for k, v in c.items() if not k.startswith("_") and k != "confidence_sum"}
        item["avg_confidence"] = round(c["confidence_sum"] / c["observations"], 2) if c["observations"] else None
        item["canonical_families"] = dict(sorted(c["canonical_families"].items()))
        item["authoritative_families"] = dict(sorted(c["authoritative_families"].items()))
        result.append(item)
    return result


def summary(path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    availability = _availability(path)
    base = {"ok": not availability.get("degraded", False), "version": VERSION, "schema_version": SCHEMA_VERSION,
            **availability, "execution_authority": False}
    if availability.get("status") != "READY":
        return {**base, "counts": {}, "family_effectiveness": [], "opportunity_clusters": {}}
    rows = _rows(path)
    missed = [r for r in rows if bool(r.get("missed_opportunity"))]
    protective = [r for r in rows if bool(r.get("protective_abstention"))]
    family_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "family": "", "abstentions_with_contributor": 0, "missed_with_contributor": 0,
        "protected_with_contributor": 0, "explicitly_blocked_abstentions": 0,
        "missed_after_explicit_block": 0, "protected_after_explicit_block": 0,
    })
    for r in rows:
        for family, detail in r["causality"]["families"].items():
            s = family_stats[family]; s["family"] = family
            s["abstentions_with_contributor"] += 1
            s["missed_with_contributor"] += int(bool(r.get("missed_opportunity")))
            s["protected_with_contributor"] += int(bool(r.get("protective_abstention")))
            if detail.get("authoritative_block"):
                s["explicitly_blocked_abstentions"] += 1
                s["missed_after_explicit_block"] += int(bool(r.get("missed_opportunity")))
                s["protected_after_explicit_block"] += int(bool(r.get("protective_abstention")))
    family_rows = []
    for s in family_stats.values():
        d = s["abstentions_with_contributor"]
        b = s["explicitly_blocked_abstentions"]
        s["missed_rate_with_contributor_pct"] = round(100.0 * s["missed_with_contributor"] / d, 2) if d else None
        s["protective_rate_with_contributor_pct"] = round(100.0 * s["protected_with_contributor"] / d, 2) if d else None
        s["missed_rate_after_explicit_block_pct"] = round(100.0 * s["missed_after_explicit_block"] / b, 2) if b else None
        family_rows.append(s)
    family_rows.sort(key=lambda x: (x["explicitly_blocked_abstentions"], x["abstentions_with_contributor"]), reverse=True)
    clusters = opportunity_clusters(path)
    return {
        **base, "status": "READY",
        "counts": {"graded_abstentions": len(rows), "missed_observations": len(missed), "protective_observations": len(protective)},
        "opportunity_clusters": {
            "count": len(clusters),
            "observations": sum(c["observations"] for c in clusters),
            "deduplication_is_analytical_only": True,
            "rule": "same ticker+direction; capture within anchor observation grading horizon",
        },
        "family_effectiveness": family_rows,
        "governance": {
            "observational_only": True, "changes_trade_decisions": False, "changes_thresholds": False,
            "changes_learning_eligibility": False, "feeds_calibration_automatically": False,
            "changes_execution_authority": False, "automatic_promotion": False,
            "explicit_blockers_not_inferred": True,
            "contributors_are_not_claimed_as_causal_without_blocked_true": True,
            "human_review_required_for_policy_change": True,
        },
    }


def detail(path: str | Path = DEFAULT_DB, limit: int = 500, classification: Optional[str] = None) -> Dict[str, Any]:
    availability = _availability(path)
    if availability.get("status") != "READY":
        return {"ok": not availability.get("degraded", False), "version": VERSION, **availability, "items": []}
    rows = list(reversed(_rows(path)))
    cls = _u(classification)
    if cls in {"MISSED", "MISSED_OPPORTUNITY"}:
        rows = [r for r in rows if bool(r.get("missed_opportunity"))]
    elif cls in {"PROTECTIVE", "PROTECTIVE_ABSTENTION"}:
        rows = [r for r in rows if bool(r.get("protective_abstention"))]
    rows = rows[:max(1, min(int(limit), 1000))]
    for r in rows:
        r.pop("gates", None)  # canonicalized output avoids mirrored path explosion
    return {"ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION, **availability,
            "items": rows, "execution_authority": False}


def cluster_detail(path: str | Path = DEFAULT_DB, limit: int = 200) -> Dict[str, Any]:
    availability = _availability(path)
    if availability.get("status") != "READY":
        return {"ok": not availability.get("degraded", False), "version": VERSION, **availability, "items": []}
    items = list(reversed(opportunity_clusters(path)))[:max(1, min(int(limit), 1000))]
    return {"ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION, **availability,
            "items": items, "execution_authority": False}
