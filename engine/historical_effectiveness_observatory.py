"""APEX 66.7.0 — Historical Effectiveness Observatory.

Read-only measurement of what APEX predicted versus governed terminal outcomes.
It does not grade, backfill, recalibrate, promote, or mutate live decisions.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .evidence_pipeline import DEFAULT_DB, _connect, readiness

VERSION = "66.7.0"
SCHEMA_VERSION = "apex.historical_effectiveness_observatory.v1"
ET = ZoneInfo("America/New_York")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(v: Any) -> dict[str, Any]:
    if isinstance(v, Mapping):
        return dict(v)
    try:
        x = json.loads(v or "{}")
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _pct(v: Any) -> float | None:
    x = _f(v)
    if x is None:
        return None
    if 0.0 <= x <= 1.0:
        x *= 100.0
    return max(0.0, min(100.0, x))


def _path(root: Mapping[str, Any], *paths: str) -> Any:
    for dotted in paths:
        cur: Any = root
        ok = True
        for key in dotted.split("."):
            if not isinstance(cur, Mapping) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur not in (None, "", [], {}):
            return cur
    return None


def _norm(v: Any, default: str = "UNKNOWN") -> str:
    s = str(v or "").strip().upper().replace(" ", "_")
    return s or default


def _session_period(ts: Any) -> str:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        d = d.astimezone(ET)
        m = d.hour * 60 + d.minute
        if 570 <= m < 585: return "OPEN_0930_0945"
        if 585 <= m < 630: return "MORNING_0945_1030"
        if 630 <= m < 690: return "LATE_MORNING_1030_1130"
        if 690 <= m < 810: return "MIDDAY_1130_1330"
        if 810 <= m < 960: return "AFTERNOON_1330_1600"
        return "OUTSIDE_RTH"
    except Exception:
        return "UNKNOWN"


def _confidence_bucket(v: Any) -> str:
    p = _pct(v)
    if p is None: return "UNKNOWN"
    lo = int(p // 10) * 10
    lo = min(lo, 90)
    return f"{lo:02d}-{lo+9 if lo < 90 else 100:02d}"


def _extract_horizons(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    thi = _path(snapshot, "trade_horizon_intelligence")
    if not isinstance(thi, Mapping):
        return {}
    hs = thi.get("horizons")
    if not isinstance(hs, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name in ("SCALP", "INTRADAY", "SWING"):
        row = hs.get(name)
        if isinstance(row, Mapping):
            direction = _norm(row.get("direction") or row.get("bias"), "UNAVAILABLE")
            if direction in {"BULLISH", "BEARISH"}:
                out[name] = {"direction": direction, "confidence": _pct(row.get("confidence"))}
    return out


def _extract_regimes(snapshot: Mapping[str, Any]) -> dict[str, str]:
    return {
        "market_regime": _norm(_path(snapshot, "market_regime", "regime", "market_state.regime", "institutional_decision_object.regime")),
        "gamma_regime": _norm(_path(snapshot, "gamma_regime", "gamma.regime", "dealer_positioning.gamma_regime", "institutional_decision_object.gamma_regime")),
        "volatility_regime": _norm(_path(snapshot, "volatility_regime", "volatility.regime", "institutional_decision_object.volatility_regime")),
        "auction_regime": _norm(_path(snapshot, "auction_regime", "auction.regime", "institutional_decision_object.auction_regime")),
    }


def _record(decision: Mapping[str, Any], grade: Mapping[str, Any]) -> dict[str, Any]:
    snap = _load(decision.get("snapshot_json"))
    out = _load(grade.get("outcome_json"))
    won = bool(out.get("direction_correct", out.get("won", False)))
    confidence = _pct(decision.get("confidence"))
    setup = _norm(_path(snap, "setup", "playbook", "strategy", "institutional_decision_object.strategy", "institutional_decision_object.playbook"))
    return {
        "decision_id": decision.get("decision_id"),
        "observed_at": decision.get("observed_at"),
        "ticker": _norm(decision.get("ticker"), "SPX"),
        "session": _norm(decision.get("session")),
        "direction": _norm(decision.get("direction")),
        "action": _norm(decision.get("action")),
        "confidence": confidence,
        "confidence_bucket": _confidence_bucket(confidence),
        "setup": setup,
        "session_period": _session_period(decision.get("observed_at")),
        "won": won,
        "directional_move": _f(out.get("directional_move")),
        "mfe": _f(out.get("mfe")),
        "mae": _f(out.get("mae")),
        "horizon_seconds": grade.get("horizon_seconds"),
        "horizons": _extract_horizons(snap),
        "regimes": _extract_regimes(snap),
    }


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    wins = sum(1 for r in rows if r["won"])
    moves = [r["directional_move"] for r in rows if r["directional_move"] is not None]
    mfes = [r["mfe"] for r in rows if r["mfe"] is not None]
    maes = [r["mae"] for r in rows if r["mae"] is not None]
    confs = [r["confidence"] for r in rows if r["confidence"] is not None]
    hit = (100.0 * wins / n) if n else None
    mean_conf = (sum(confs) / len(confs)) if confs else None
    return {
        "sample_size": n,
        "wins": wins,
        "losses": n - wins,
        "hit_rate": round(hit, 2) if hit is not None else None,
        "mean_evidence_score": round(mean_conf, 2) if mean_conf is not None else None,
        "calibration_gap_points": round(mean_conf - hit, 2) if mean_conf is not None and hit is not None else None,
        "average_directional_move": round(sum(moves) / len(moves), 4) if moves else None,
        "average_mfe": round(sum(mfes) / len(mfes), 4) if mfes else None,
        "average_mae": round(sum(maes) / len(maes), 4) if maes else None,
    }


def _breakdown(rows: list[dict[str, Any]], key_fn, minimum_sample: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(key_fn(r) or "UNKNOWN")].append(r)
    out = []
    for key, group in groups.items():
        item = {"value": key, **_stats(group)}
        item["qualified"] = len(group) >= minimum_sample
        out.append(item)
    out.sort(key=lambda x: (x["qualified"], x["sample_size"], x["hit_rate"] or -1), reverse=True)
    return out


def _horizon_breakdown(rows: list[dict[str, Any]], minimum_sample: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        for name, horizon in r.get("horizons", {}).items():
            direction = horizon.get("direction") if isinstance(horizon, Mapping) else None
            if direction not in {"BULLISH", "BEARISH"}: continue
            canonical = r.get("direction")
            if canonical not in {"BULLISH", "BEARISH"}: continue
            derived = dict(r)
            # Grade outcome is relative to canonical direction. Flip correctness when
            # a captured horizon explicitly opposed that canonical prediction.
            derived["won"] = r["won"] if direction == canonical else not r["won"]
            derived["confidence"] = horizon.get("confidence") if isinstance(horizon, Mapping) else None
            groups[name].append(derived)
    out = []
    for name in ("SCALP", "INTRADAY", "SWING"):
        g = groups.get(name, [])
        out.append({"value": name, **_stats(g), "qualified": len(g) >= minimum_sample})
    return out


def load_graded_records(*, path: str | Path = DEFAULT_DB, symbol: str = "SPX", limit: int = 10000) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return canonical governed graded records for read-only effectiveness audits.

    This is the shared measurement boundary for 66.7+ observatories; it does not
    infer, backfill, grade, or mutate outcomes.
    """
    limit = max(1, min(int(limit), 50000))
    rows: list[dict[str, Any]] = []
    excluded: dict[str, int] = defaultdict(int)
    with _connect(path) as c:
        joined = c.execute("""
            SELECT d.*, g.graded_at, g.status AS grade_status, g.exclusion_reason,
                   g.horizon_seconds, g.outcome_json
            FROM decisions d
            LEFT JOIN grading_results g ON g.decision_id=d.decision_id
            WHERE UPPER(d.ticker)=UPPER(?)
            ORDER BY d.observed_at DESC LIMIT ?
        """, (symbol, limit)).fetchall()
        for x in joined:
            d = dict(x)
            if d.get("grade_status") == "GRADED":
                rows.append(_record(d, d))
            elif d.get("grade_status") == "EXCLUDED":
                excluded[str(d.get("exclusion_reason") or "UNKNOWN")] += 1
    return rows, dict(sorted(excluded.items()))


def build_observatory(*, path: str | Path = DEFAULT_DB, symbol: str = "SPX", minimum_sample: int = 20, limit: int = 10000) -> dict[str, Any]:
    minimum_sample = max(1, int(minimum_sample))
    rows, excluded = load_graded_records(path=path, symbol=symbol, limit=limit)

    overall = _stats(rows)
    qualified = overall["sample_size"] >= minimum_sample
    state = "READY" if qualified else ("COLLECTING" if rows else "WAITING_FOR_GRADED_OUTCOMES")
    return {
        "ok": True,
        "status": state,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "symbol": symbol.upper(),
        "minimum_sample": minimum_sample,
        "overall": overall,
        "breakdowns": {
            "horizon": _horizon_breakdown(rows, minimum_sample),
            "confidence_bucket": _breakdown(rows, lambda r: r["confidence_bucket"], minimum_sample),
            "setup": _breakdown(rows, lambda r: r["setup"], minimum_sample),
            "session_period": _breakdown(rows, lambda r: r["session_period"], minimum_sample),
            "market_regime": _breakdown(rows, lambda r: r["regimes"]["market_regime"], minimum_sample),
            "gamma_regime": _breakdown(rows, lambda r: r["regimes"]["gamma_regime"], minimum_sample),
            "volatility_regime": _breakdown(rows, lambda r: r["regimes"]["volatility_regime"], minimum_sample),
            "auction_regime": _breakdown(rows, lambda r: r["regimes"]["auction_regime"], minimum_sample),
        },
        "exclusions": excluded,
        "evidence_readiness": readiness(path),
        "interpretation": {
            "evidence_score": "APEX internal conviction/evidence score captured at decision time; not asserted to be a calibrated probability.",
            "hit_rate": "Observed directional correctness among governed GRADED outcomes only.",
            "calibration_gap_points": "Mean evidence score minus observed hit rate. This is a diagnostic gap, not an automatic recalibration instruction.",
            "horizon": "Uses horizon directions captured inside the historical decision snapshot. No horizon is inferred from elapsed time when absent.",
        },
        "guardrails": {
            "read_only": True,
            "grades_outcomes": False,
            "backfills_history": False,
            "changes_trade_decisions": False,
            "changes_execution_authority": False,
            "automatic_calibration": False,
            "requires_governed_graded_outcomes": True,
        },
    }


def health(*, path: str | Path = DEFAULT_DB, symbol: str = "SPX") -> dict[str, Any]:
    x = build_observatory(path=path, symbol=symbol, minimum_sample=20, limit=1000)
    return {
        "ok": x["ok"], "status": x["status"], "version": VERSION,
        "graded_sample_size": x["overall"]["sample_size"],
        "evidence_pipeline_status": x["evidence_readiness"].get("status"),
        "generated_at": x["generated_at"], "read_only": True,
    }
