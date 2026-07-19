"""APEX 18.0 Adaptive Intelligence.

Governed, evidence-only learning layer. It stores completed-session profiles and
outcomes, retrieves similar historical sessions, calibrates confidence, ranks
playbooks, computes an institutional edge score, and generates post-session
review/journal artifacts. It never mutates broker state or submits orders.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from . import institutional_governance as gov

VERSION = "18.0_ADAPTIVE_INTELLIGENCE"
FEATURE_KEYS = (
    "overnight_inventory", "vix", "gamma_regime", "auction_state",
    "volume_profile", "order_flow", "volatility", "trend_strength",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(gov.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def _hash(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode()).hexdigest()


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clip(v: Any, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, _num(v)))


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS adaptive_session_memory (
          session_id TEXT PRIMARY KEY, session_date TEXT NOT NULL UNIQUE,
          symbol TEXT NOT NULL, regime TEXT, profile_json TEXT NOT NULL,
          features_json TEXT NOT NULL, outcome_json TEXT NOT NULL,
          evidence_hash TEXT NOT NULL, recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS adaptive_trade_reviews (
          review_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL UNIQUE,
          review_json TEXT NOT NULL, evidence_hash TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS adaptive_daily_journals (
          journal_id TEXT PRIMARY KEY, session_date TEXT NOT NULL UNIQUE,
          journal_json TEXT NOT NULL, evidence_hash TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS adaptive_recommendations (
          recommendation_id TEXT PRIMARY KEY, recommendation_type TEXT NOT NULL,
          payload_json TEXT NOT NULL, evidence_hash TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'SHADOW', recorded_at TEXT NOT NULL
        );
        """)


def status() -> dict:
    init_db()
    with _conn() as c:
        sessions = c.execute("SELECT COUNT(*) n FROM adaptive_session_memory").fetchone()["n"]
        reviews = c.execute("SELECT COUNT(*) n FROM adaptive_trade_reviews").fetchone()["n"]
        journals = c.execute("SELECT COUNT(*) n FROM adaptive_daily_journals").fetchone()["n"]
    return {
        "status": "READY", "engine": "ADAPTIVE_INTELLIGENCE", "build_version": VERSION,
        "sessions_recorded": sessions, "trade_reviews": reviews, "journals": journals,
        "learning_mode": "GOVERNED_SHADOW", "minimum_calibration_sample": 30,
        "automatic_parameter_mutation": False, "automatic_order_submission_enabled": False,
        "human_confirmation_required": True, "production_effect": "ADVISORY_ONLY",
    }


def _features(profile: dict) -> dict[str, float]:
    supplied = profile.get("features") or {}
    out: dict[str, float] = {}
    for key in FEATURE_KEYS:
        value = supplied.get(key, profile.get(key))
        if isinstance(value, str):
            # Stable categorical embedding; deterministic and bounded.
            value = int(hashlib.sha256(value.upper().encode()).hexdigest()[:8], 16) % 101
        out[key] = _clip(value)
    return out


def record_session(payload: dict) -> dict:
    init_db()
    session_date = str(payload.get("session_date") or "").strip()
    if not session_date:
        return {"ok": False, "status": "REJECTED", "reason": "SESSION_DATE_REQUIRED"}
    profile = payload.get("profile") or {}
    outcome = payload.get("outcome") or {}
    if not profile:
        return {"ok": False, "status": "REJECTED", "reason": "PROFILE_REQUIRED"}
    record = {
        "session_date": session_date, "symbol": str(payload.get("symbol") or "SPX").upper(),
        "regime": str(profile.get("regime") or "UNKNOWN"), "profile": profile,
        "features": _features(profile), "outcome": outcome,
    }
    digest = _hash(record)
    sid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apex-session:{session_date}:{record['symbol']}"))
    with _conn() as c:
        existing = c.execute("SELECT evidence_hash FROM adaptive_session_memory WHERE session_date=?", (session_date,)).fetchone()
        if existing:
            return {"ok": True, "created": False, "status": "IMMUTABLE_EXISTS", "session_id": sid,
                    "same_evidence": existing["evidence_hash"] == digest}
        c.execute("INSERT INTO adaptive_session_memory VALUES (?,?,?,?,?,?,?,?,?)", (
            sid, session_date, record["symbol"], record["regime"], _json(profile),
            _json(record["features"]), _json(outcome), digest, _now()))
    return {"ok": True, "created": True, "status": "RECORDED", "session_id": sid, "evidence_hash": digest}


def sessions(limit: int = 100) -> list[dict]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM adaptive_session_memory ORDER BY session_date DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    return [{**dict(r), "profile": json.loads(r["profile_json"]), "features": json.loads(r["features_json"]),
             "outcome": json.loads(r["outcome_json"])} for r in rows]


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(a.get(k, 0.0) ** 2 for k in keys))
    nb = math.sqrt(sum(b.get(k, 0.0) ** 2 for k in keys))
    return 0.0 if not na or not nb else dot / (na * nb)


def similar_sessions(profile: dict, top_k: int = 5, exclude_date: str | None = None) -> dict:
    query = _features(profile)
    matches = []
    for row in sessions(500):
        if exclude_date and row["session_date"] == exclude_date:
            continue
        similarity = round(_cosine(query, row["features"]) * 100, 2)
        matches.append({"session_id": row["session_id"], "session_date": row["session_date"],
                        "regime": row["regime"], "similarity": similarity,
                        "outcome": row["outcome"], "profile": row["profile"]})
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return {"ok": True, "status": "READY" if matches else "COLLECTING", "query_features": query,
            "matches": matches[:max(1, min(top_k, 25))], "sample_size": len(matches)}


def confidence_calibration(symbol: str = "SPX") -> dict:
    rows = [r for r in sessions(500) if r["symbol"] == symbol.upper()]
    observations = []
    for r in rows:
        raw = r["outcome"].get("raw_confidence")
        won = r["outcome"].get("won")
        if raw is not None and isinstance(won, bool):
            observations.append((_clip(raw), 100.0 if won else 0.0))
    bins = []
    for low in range(0, 100, 10):
        vals = [x for x in observations if low <= x[0] <= (100 if low == 90 else low + 9.999)]
        if vals:
            avg_raw = sum(x[0] for x in vals) / len(vals)
            accuracy = sum(x[1] for x in vals) / len(vals)
            bins.append({"range": f"{low}-{low+9}", "count": len(vals), "avg_raw": round(avg_raw, 2),
                         "observed_accuracy": round(accuracy, 2), "calibration_error": round(avg_raw - accuracy, 2)})
    total = len(observations)
    mae = (sum(abs(b["calibration_error"]) * b["count"] for b in bins) / total) if total else None
    return {"ok": True, "status": "READY" if total >= 30 else "COLLECTING", "symbol": symbol.upper(),
            "sample_size": total, "minimum_sample": 30, "bins": bins,
            "mean_absolute_calibration_error": round(mae, 2) if mae is not None else None}


def calibrate(raw_confidence: float, symbol: str = "SPX") -> dict:
    raw = _clip(raw_confidence)
    report = confidence_calibration(symbol)
    if report["sample_size"] < report["minimum_sample"]:
        return {"raw_confidence": raw, "calibrated_confidence": raw, "status": "UNCALIBRATED",
                "reason": "INSUFFICIENT_VALIDATED_SAMPLE", "sample_size": report["sample_size"]}
    target = next((b for b in report["bins"] if int(b["range"].split("-")[0]) <= raw <= int(b["range"].split("-")[1])), None)
    calibrated = target["observed_accuracy"] if target else raw
    return {"raw_confidence": raw, "calibrated_confidence": round(calibrated, 2), "status": "CALIBRATED",
            "sample_size": report["sample_size"]}


def playbook_rankings(symbol: str = "SPX", window: int = 90) -> dict:
    rows = [r for r in sessions(500) if r["symbol"] == symbol.upper()][:max(1, window)]
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        pb = str(r["outcome"].get("playbook") or r["profile"].get("playbook") or "").strip()
        if pb:
            grouped.setdefault(pb, []).append(r["outcome"])
    rankings = []
    for pb, vals in grouped.items():
        graded = [v for v in vals if isinstance(v.get("won"), bool)]
        wins = sum(1 for v in graded if v["won"])
        avg_r = sum(_num(v.get("r_multiple")) for v in graded) / len(graded) if graded else 0
        score = (wins / len(graded) * 70 + max(-2, min(3, avg_r)) / 3 * 30) if graded else 0
        rankings.append({"playbook": pb, "trades": len(graded), "win_rate": round(wins / len(graded) * 100, 2) if graded else None,
                         "average_r": round(avg_r, 3) if graded else None, "adaptive_score": round(max(0, score), 2),
                         "eligible": len(graded) >= 10})
    rankings.sort(key=lambda x: (x["eligible"], x["adaptive_score"]), reverse=True)
    return {"ok": True, "status": "READY" if rankings else "COLLECTING", "symbol": symbol.upper(),
            "window": window, "rankings": rankings,
            "governance": "ADVISORY_ONLY_NO_AUTOMATIC_WEIGHT_MUTATION"}


def edge_score(components: dict) -> dict:
    weights = {"market_quality": .18, "liquidity": .14, "flow": .16, "risk": .18,
               "volatility": .10, "execution": .12, "historical_similarity": .12}
    available = {k: _clip(components[k]) for k in weights if components.get(k) is not None}
    denominator = sum(weights[k] for k in available)
    score = sum(available[k] * weights[k] for k in available) / denominator if denominator else 0.0
    blockers = list(components.get("blockers") or [])
    if blockers:
        score = min(score, 49.0)
    classification = "HIGH" if score >= 80 else "MODERATE" if score >= 65 else "LOW" if score >= 50 else "STAND_DOWN"
    return {"institutional_edge_score": round(score, 2), "classification": classification,
            "components": available, "blockers": blockers, "trade_permission": not blockers and score >= 65}


def self_evaluate(payload: dict) -> dict:
    trade_id = str(payload.get("trade_id") or "").strip()
    if not trade_id:
        return {"ok": False, "status": "REJECTED", "reason": "TRADE_ID_REQUIRED"}
    expected = payload.get("expected") or {}
    actual = payload.get("actual") or {}
    entry_delay = _num(actual.get("entry_time_seconds")) - _num(expected.get("entry_time_seconds"))
    exit_eff = _num(actual.get("captured_move_pct"))
    review = {
        "trade_id": trade_id,
        "entry_timing": "EARLY" if entry_delay < -15 else "LATE" if entry_delay > 15 else "ON_TIME",
        "stop_assessment": "TOO_TIGHT" if actual.get("stopped_then_target") else "ACCEPTABLE",
        "exit_efficiency_pct": round(exit_eff, 2),
        "confidence_error": round(_num(payload.get("raw_confidence")) - (100 if actual.get("won") else 0), 2),
        "primary_mistake": str(payload.get("primary_mistake") or "NONE_IDENTIFIED"),
        "lesson": str(payload.get("lesson") or "INSUFFICIENT_EVIDENCE"),
        "evidence": {"expected": expected, "actual": actual},
    }
    digest = _hash(review); rid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apex-review:{trade_id}"))
    init_db()
    with _conn() as c:
        existing = c.execute("SELECT evidence_hash FROM adaptive_trade_reviews WHERE trade_id=?", (trade_id,)).fetchone()
        if existing:
            return {"ok": True, "created": False, "status": "IMMUTABLE_EXISTS", "review_id": rid,
                    "same_evidence": existing["evidence_hash"] == digest}
        c.execute("INSERT INTO adaptive_trade_reviews VALUES (?,?,?,?,?)", (rid, trade_id, _json(review), digest, _now()))
    return {"ok": True, "created": True, "status": "RECORDED", "review_id": rid, "review": review}


def daily_journal(payload: dict) -> dict:
    date = str(payload.get("session_date") or "").strip()
    if not date:
        return {"ok": False, "status": "REJECTED", "reason": "SESSION_DATE_REQUIRED"}
    journal = {
        "session_date": date, "morning_thesis": payload.get("morning_thesis") or "UNAVAILABLE",
        "market_structure": payload.get("market_structure") or "UNAVAILABLE",
        "trades": payload.get("trades") or [], "mistakes": payload.get("mistakes") or [],
        "lessons": payload.get("lessons") or [], "tomorrow_focus": payload.get("tomorrow_focus") or [],
        "generated_from_validated_evidence": bool(payload.get("validated_evidence")),
    }
    digest = _hash(journal); jid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apex-journal:{date}"))
    init_db()
    with _conn() as c:
        existing = c.execute("SELECT evidence_hash FROM adaptive_daily_journals WHERE session_date=?", (date,)).fetchone()
        if existing:
            return {"ok": True, "created": False, "status": "IMMUTABLE_EXISTS", "journal_id": jid,
                    "same_evidence": existing["evidence_hash"] == digest}
        c.execute("INSERT INTO adaptive_daily_journals VALUES (?,?,?,?,?)", (jid, date, _json(journal), digest, _now()))
    return {"ok": True, "created": True, "status": "RECORDED", "journal_id": jid, "journal": journal}


def dashboard(symbol: str = "SPX", current_profile: dict | None = None, raw_confidence: float | None = None) -> dict:
    current_profile = current_profile or {}
    similarity = similar_sessions(current_profile, 5) if current_profile else {"status": "UNAVAILABLE", "matches": [], "sample_size": 0}
    similarity_score = similarity.get("matches", [{}])[0].get("similarity") if similarity.get("matches") else None
    return {
        "ok": True, "status": "READY", "version": VERSION, "system_status": status(),
        "similar_sessions": similarity,
        "confidence": calibrate(raw_confidence, symbol) if raw_confidence is not None else {"status": "UNAVAILABLE"},
        "calibration": confidence_calibration(symbol),
        "playbook_rankings": playbook_rankings(symbol),
        "edge": edge_score({"historical_similarity": similarity_score}),
        "safety": {"advisory_only": True, "automatic_parameter_mutation": False,
                   "automatic_order_submission_enabled": False, "human_confirmation_required": True},
    }
