"""APEX 18.3.0 — Strategy Discovery Engine.

Discovers governed, statistically mature premium-strategy patterns from graded
Institutional Learning samples. Discovery is advisory: patterns must be
explicitly promoted before appearing in the active institutional playbook and
never bypass existing Premium Discipline, risk, or execution controls.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import statistics
from typing import Any, Dict, List, Optional, Tuple

from .institutional_learning_engine import market_fingerprint

VERSION = "18.3.0_STRATEGY_DISCOVERY_ENGINE"


def _j(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def _loads(v: Any, default: Any) -> Any:
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except Exception:
        return default


def _pattern_id(signature: Dict[str, Any]) -> str:
    return "PAT-" + hashlib.sha256(_j(signature).encode("utf-8")).hexdigest()[:16].upper()


def _confidence_interval(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"low": 0.0, "high": 0.0}
    mean = statistics.fmean(values)
    if len(values) < 2:
        return {"low": round(mean, 2), "high": round(mean, 2)}
    se = statistics.stdev(values) / math.sqrt(len(values))
    margin = 1.96 * se
    return {"low": round(mean - margin, 2), "high": round(mean + margin, 2)}


def _max_drawdown(values: List[float]) -> float:
    equity = peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(abs(worst), 2)


def _drift_status(values: List[float]) -> str:
    if len(values) < 8:
        return "STABLE"
    cut = max(3, len(values) // 3)
    recent = statistics.fmean(values[-cut:])
    prior = statistics.fmean(values[:-cut]) if values[:-cut] else recent
    scale = max(abs(prior), 1.0)
    change = (recent - prior) / scale
    if change >= 0.25:
        return "IMPROVING"
    if change <= -0.50:
        return "DEGRADING"
    if change <= -0.20:
        return "WEAKENING"
    return "STABLE"


class StrategyDiscoveryStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "apex_tracking.db")
        self._init()

    def _c(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._c() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS strategy_discovery_patterns(
                pattern_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                signature_json TEXT NOT NULL, metrics_json TEXT NOT NULL,
                status TEXT NOT NULL, promoted INTEGER NOT NULL DEFAULT 0,
                promoted_at TEXT, promoted_by TEXT, retired_at TEXT, retired_by TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS strategy_discovery_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                sample_count INTEGER NOT NULL, min_sample INTEGER NOT NULL,
                result_json TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS strategy_discovery_audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                pattern_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
                details_json TEXT NOT NULL)""")

    def discover(self, *, min_sample: int = 20, lookback: int = 5000) -> Dict[str, Any]:
        min_sample = max(5, int(min_sample))
        lookback = max(1, min(int(lookback), 50000))
        with self._c() as c:
            rows = c.execute("""SELECT * FROM institutional_learning_samples
                WHERE pnl IS NOT NULL ORDER BY created_at ASC LIMIT ?""", (lookback,)).fetchall()

        groups: Dict[Tuple[str, ...], List[sqlite3.Row]] = {}
        for row in rows:
            fp = _loads(row["fingerprint_json"], {})
            features = _loads(row["features_json"], {})
            signature = (
                str(row["ticker"]).upper(), str(row["strategy"]).upper(),
                str(fp.get("regime") or "UNKNOWN").upper(),
                str(fp.get("direction") or "NEUTRAL").upper(),
                str(fp.get("auction") or "UNKNOWN").upper(),
                str(fp.get("gamma") or "UNKNOWN").upper(),
                str(fp.get("volatility") or "UNKNOWN").upper(),
                str(fp.get("time_bucket") or features.get("time_bucket") or "UNKNOWN").upper(),
            )
            groups.setdefault(signature, []).append(row)

        now = dt.datetime.now(dt.timezone.utc).isoformat()
        patterns: List[Dict[str, Any]] = []
        with self._c() as c:
            for key, sample_rows in groups.items():
                values = [float(r["pnl"]) for r in sample_rows]
                winners = [v for v in values if v > 0]
                losers = [v for v in values if v < 0]
                signature = dict(zip(
                    ["ticker", "strategy", "regime", "direction", "auction", "gamma", "volatility", "time_bucket"], key))
                samples = len(values)
                win_rate = sum(v > 0 for v in values) / samples
                avg_pnl = statistics.fmean(values)
                drawdown = _max_drawdown(values)
                drift = _drift_status(values)
                maturity = min(1.0, samples / float(min_sample))
                stability = max(0.0, 1.0 - drawdown / max(abs(sum(values)), 100.0))
                discovery_score = 100 * (
                    0.34 * min(1.0, max(0.0, (avg_pnl + 100.0) / 300.0)) +
                    0.24 * win_rate + 0.20 * maturity + 0.12 * stability +
                    0.10 * ({"IMPROVING": 1.0, "STABLE": 0.75, "WEAKENING": 0.35, "DEGRADING": 0.0}.get(drift, 0.5))
                )
                status = "DEVELOPING"
                if samples >= min_sample and avg_pnl > 0 and win_rate >= 0.50 and drift != "DEGRADING":
                    status = drift if drift in {"IMPROVING", "WEAKENING"} else "STABLE"
                elif samples >= min_sample and (avg_pnl <= 0 or drift == "DEGRADING"):
                    status = "DEGRADING"
                metrics = {
                    "sample_count": samples, "win_rate": round(win_rate, 4),
                    "average_pnl": round(avg_pnl, 2), "average_winner": round(statistics.fmean(winners), 2) if winners else 0.0,
                    "average_loser": round(statistics.fmean(losers), 2) if losers else 0.0,
                    "total_pnl": round(sum(values), 2), "expected_value": round(avg_pnl, 2),
                    "confidence_interval_95": _confidence_interval(values), "maximum_drawdown": drawdown,
                    "last_observed_at": sample_rows[-1]["created_at"], "drift_status": drift,
                    "discovery_score": round(discovery_score, 2),
                }
                pid = _pattern_id(signature)
                existing = c.execute("SELECT promoted,status FROM strategy_discovery_patterns WHERE pattern_id=?", (pid,)).fetchone()
                promoted = int(existing["promoted"]) if existing else 0
                final_status = "RETIRED" if existing and existing["status"] == "RETIRED" else status
                c.execute("""INSERT INTO strategy_discovery_patterns(pattern_id,created_at,updated_at,signature_json,metrics_json,status,promoted)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(pattern_id) DO UPDATE SET
                    updated_at=excluded.updated_at,signature_json=excluded.signature_json,
                    metrics_json=excluded.metrics_json,status=CASE WHEN strategy_discovery_patterns.status='RETIRED' THEN 'RETIRED' ELSE excluded.status END""",
                    (pid, now, now, _j(signature), _j(metrics), final_status, promoted))
                patterns.append({"pattern_id": pid, "signature": signature, "metrics": metrics,
                                 "status": final_status, "promoted": bool(promoted)})
            patterns.sort(key=lambda p: (p["status"] not in {"DEVELOPING", "DEGRADING", "RETIRED"}, p["metrics"]["discovery_score"], p["metrics"]["sample_count"]), reverse=True)
            result = {"version": VERSION, "advisory_only": True, "generated_at": now,
                      "sample_count": len(rows), "pattern_count": len(patterns), "min_sample": min_sample,
                      "readiness": "READY" if any(p["status"] in {"STABLE", "IMPROVING", "WEAKENING"} for p in patterns) else "DEVELOPING",
                      "patterns": patterns, "best_pattern": patterns[0] if patterns else None,
                      "governance": {"automatic_promotion": False, "operator_promotion_required": True,
                                     "bypasses_risk_controls": False, "broker_authority": False}}
            cur = c.execute("INSERT INTO strategy_discovery_runs(created_at,sample_count,min_sample,result_json) VALUES(?,?,?,?)",
                            (now, len(rows), min_sample, _j(result)))
            result["run_id"] = cur.lastrowid
        return result

    def patterns(self, limit: int = 100, *, promoted_only: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM strategy_discovery_patterns"
        params: List[Any] = []
        if promoted_only:
            sql += " WHERE promoted=1 AND status!='RETIRED'"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._c() as c:
            rows = c.execute(sql, params).fetchall()
        return [{"pattern_id": r["pattern_id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
                 "signature": _loads(r["signature_json"], {}), "metrics": _loads(r["metrics_json"], {}),
                 "status": r["status"], "promoted": bool(r["promoted"]), "promoted_at": r["promoted_at"],
                 "promoted_by": r["promoted_by"]} for r in rows]

    def promote(self, pattern_id: str, actor: str = "operator") -> Dict[str, Any]:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._c() as c:
            row = c.execute("SELECT * FROM strategy_discovery_patterns WHERE pattern_id=?", (pattern_id,)).fetchone()
            if not row:
                raise ValueError("Pattern was not found.")
            metrics = _loads(row["metrics_json"], {})
            if row["status"] in {"DEVELOPING", "DEGRADING", "RETIRED"}:
                raise ValueError(f"Pattern status {row['status']} is not eligible for promotion.")
            if float(metrics.get("expected_value") or 0) <= 0:
                raise ValueError("Only positive-expectancy patterns may be promoted.")
            c.execute("UPDATE strategy_discovery_patterns SET promoted=1,promoted_at=?,promoted_by=? WHERE pattern_id=?",
                      (now, actor[:120], pattern_id))
            c.execute("INSERT INTO strategy_discovery_audit(created_at,pattern_id,action,actor,details_json) VALUES(?,?,?,?,?)",
                      (now, pattern_id, "PROMOTE", actor[:120], _j({"metrics": metrics})))
        return {"pattern_id": pattern_id, "promoted": True, "promoted_at": now, "promoted_by": actor[:120]}

    def retire(self, pattern_id: str, actor: str = "operator", reason: str = "") -> Dict[str, Any]:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._c() as c:
            cur = c.execute("UPDATE strategy_discovery_patterns SET promoted=0,status='RETIRED',retired_at=?,retired_by=? WHERE pattern_id=?",
                            (now, actor[:120], pattern_id))
            if cur.rowcount != 1:
                raise ValueError("Pattern was not found.")
            c.execute("INSERT INTO strategy_discovery_audit(created_at,pattern_id,action,actor,details_json) VALUES(?,?,?,?,?)",
                      (now, pattern_id, "RETIRE", actor[:120], _j({"reason": reason[:500]})))
        return {"pattern_id": pattern_id, "status": "RETIRED", "retired_at": now}

    def playbook(self) -> Dict[str, Any]:
        patterns = self.patterns(500, promoted_only=True)
        by_strategy: Dict[str, List[Dict[str, Any]]] = {}
        for pattern in patterns:
            by_strategy.setdefault(pattern["signature"].get("strategy", "UNKNOWN"), []).append(pattern)
        for items in by_strategy.values():
            items.sort(key=lambda p: (p["metrics"].get("discovery_score", 0), p["metrics"].get("expected_value", 0)), reverse=True)
        return {"version": VERSION, "advisory_only": True, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "active_pattern_count": len(patterns), "strategies": by_strategy, "patterns": patterns}

    def audit(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._c() as c:
            rows = c.execute("SELECT * FROM strategy_discovery_audit ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [dict(r) | {"details": _loads(r["details_json"], {})} for r in rows]


def match_current_market(store: StrategyDiscoveryStore, context: Dict[str, Any], *, limit: int = 10) -> Dict[str, Any]:
    fp = market_fingerprint(context)
    candidates = store.patterns(1000, promoted_only=True)
    matches = []
    fields = ["regime", "direction", "auction", "gamma", "volatility", "time_bucket"]
    for pattern in candidates:
        sig = pattern["signature"]
        comparable = [field for field in fields if fp.get(field) not in {None, "UNKNOWN"} and sig.get(field) not in {None, "UNKNOWN"}]
        score = sum(fp.get(field) == sig.get(field) for field in comparable) / len(comparable) if comparable else 0.0
        matches.append({**pattern, "similarity_score": round(score, 4)})
    matches.sort(key=lambda p: (p["similarity_score"], p["metrics"].get("discovery_score", 0)), reverse=True)
    return {"current_fingerprint": fp, "matches": matches[:max(1, min(limit, 100))],
            "closest_pattern": matches[0] if matches else None, "advisory_only": True}


def build_strategy_discovery(store: StrategyDiscoveryStore, current_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    patterns = store.patterns(100)
    result = {"version": VERSION, "advisory_only": True, "patterns": patterns,
              "pattern_count": len(patterns), "institutional_playbook": store.playbook(),
              "pattern_drift": {p["pattern_id"]: p["metrics"].get("drift_status", p["status"]) for p in patterns}}
    if current_context is not None:
        result["pattern_similarity"] = match_current_market(store, current_context)
    return result
