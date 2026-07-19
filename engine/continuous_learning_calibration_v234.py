"""APEX 23.4 Continuous Learning & Confidence Calibration.

Advisory-only learning layer. It records graded outcomes, computes calibration and
performance summaries, detects drift, and emits recommendations that require
explicit human approval. It never mutates production weights or execution state.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from .institutional_playbook_engine_v233 import build_institutional_playbooks
from .institutional_regime_intelligence_v231 import build_regime_intelligence
from .institutional_trading_brain_v230 import build_institutional_trading_brain

VERSION = "16.4.0_CONTINUOUS_LEARNING_CONFIDENCE_CALIBRATION"
SEMANTIC_VERSION = "16.4.0"
SCHEMA_VERSION = "apex.continuous_learning_calibration.v1"
MIN_PROVISIONAL = 5
MIN_ACTIVE = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> str:
    return os.getenv("DB_PATH", "apex_tracking.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS apex_learning_outcomes_v234(
          outcome_id TEXT PRIMARY KEY,
          ticker TEXT NOT NULL,
          observed_at TEXT NOT NULL,
          graded_at TEXT NOT NULL,
          playbook_id TEXT NOT NULL,
          regime TEXT NOT NULL,
          forecast_scenario TEXT NOT NULL,
          stated_confidence REAL NOT NULL,
          won INTEGER NOT NULL,
          realized_r REAL NOT NULL,
          max_favorable_excursion REAL,
          max_adverse_excursion REAL,
          duration_minutes REAL,
          source_id TEXT,
          metadata_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          UNIQUE(ticker, observed_at, playbook_id, source_id)
        );
        CREATE INDEX IF NOT EXISTS idx_learning_v234_time ON apex_learning_outcomes_v234(ticker, observed_at);
        CREATE INDEX IF NOT EXISTS idx_learning_v234_playbook ON apex_learning_outcomes_v234(playbook_id, regime);
        CREATE TABLE IF NOT EXISTS apex_learning_recommendations_v234(
          recommendation_id TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          scope TEXT NOT NULL,
          subject TEXT NOT NULL,
          current_value REAL,
          proposed_value REAL,
          reason TEXT NOT NULL,
          evidence_count INTEGER NOT NULL,
          status TEXT NOT NULL,
          reviewed_at TEXT,
          reviewed_by TEXT,
          integrity_hash TEXT NOT NULL
        );
        """)


def record_outcome(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Record a sanitized, already-matured outcome. No live-decision mutation."""
    init_db()
    required = ("observed_at", "playbook_id", "regime", "forecast_scenario", "stated_confidence", "won", "realized_r")
    missing = [k for k in required if payload.get(k) is None]
    if missing:
        return {"ok": False, "status": "REJECTED", "error": "MISSING_REQUIRED_FIELDS", "missing": missing}
    confidence = max(0.0, min(100.0, float(payload["stated_confidence"])))
    won = 1 if bool(payload["won"]) else 0
    row = {
        "outcome_id": str(uuid.uuid4()), "ticker": str(payload.get("ticker") or "SPX"),
        "observed_at": str(payload["observed_at"]), "graded_at": _now(),
        "playbook_id": str(payload["playbook_id"]), "regime": str(payload["regime"]),
        "forecast_scenario": str(payload["forecast_scenario"]), "stated_confidence": confidence,
        "won": won, "realized_r": float(payload["realized_r"]),
        "max_favorable_excursion": payload.get("max_favorable_excursion"),
        "max_adverse_excursion": payload.get("max_adverse_excursion"),
        "duration_minutes": payload.get("duration_minutes"), "source_id": payload.get("source_id"),
        "metadata": dict(payload.get("metadata") or {}),
    }
    row["integrity_hash"] = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
    try:
        with _conn() as c:
            c.execute("INSERT INTO apex_learning_outcomes_v234 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                row["outcome_id"], row["ticker"], row["observed_at"], row["graded_at"], row["playbook_id"], row["regime"],
                row["forecast_scenario"], row["stated_confidence"], row["won"], row["realized_r"],
                row["max_favorable_excursion"], row["max_adverse_excursion"], row["duration_minutes"], row["source_id"],
                json.dumps(row["metadata"], sort_keys=True, default=str), row["integrity_hash"]
            ))
    except sqlite3.IntegrityError:
        return {"ok": True, "status": "IMMUTABLE_EXISTS", "production_effect": "NONE"}
    return {"ok": True, "status": "RECORDED", "outcome_id": row["outcome_id"], "integrity_hash": row["integrity_hash"], "production_effect": "NONE"}


def _rows(ticker: str = "SPX", before: Optional[str] = None) -> list[dict[str, Any]]:
    init_db(); params: list[Any] = [ticker]; where = "ticker=?"
    if before:
        where += " AND observed_at<?"; params.append(before)
    with _conn() as c:
        return [dict(x) for x in c.execute(f"SELECT * FROM apex_learning_outcomes_v234 WHERE {where} ORDER BY observed_at", params).fetchall()]


def _group(rows: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows: groups.setdefault(str(r.get(key) or "UNKNOWN"), []).append(r)
    out=[]
    for name, items in sorted(groups.items()):
        n=len(items); wins=sum(int(x["won"]) for x in items); rs=[float(x["realized_r"]) for x in items]
        out.append({key:name,"samples":n,"wins":wins,"win_rate":round(100*wins/n,2),"average_r":round(sum(rs)/n,3),"expectancy_r":round(sum(rs)/n,3)})
    return out


def _calibration(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    buckets=[]
    for low in range(0,100,10):
        items=[r for r in rows if low <= float(r["stated_confidence"]) < low+10 or (low==90 and float(r["stated_confidence"])==100)]
        if not items: continue
        predicted=sum(float(x["stated_confidence"]) for x in items)/len(items); actual=100*sum(int(x["won"]) for x in items)/len(items)
        buckets.append({"bucket":f"{low}-{low+9 if low<90 else 100}","samples":len(items),"predicted":round(predicted,2),"actual":round(actual,2),"error":round(actual-predicted,2)})
    brier=round(sum((float(r["stated_confidence"])/100-int(r["won"]))**2 for r in rows)/len(rows),4) if rows else None
    mae=round(sum(abs((float(r["stated_confidence"])/100)-int(r["won"])) for r in rows)/len(rows),4) if rows else None
    state="ACTIVE" if len(rows)>=MIN_ACTIVE else "PROVISIONAL" if len(rows)>=MIN_PROVISIONAL else "DORMANT"
    return {"state":state,"samples":len(rows),"minimum_provisional":MIN_PROVISIONAL,"minimum_active":MIN_ACTIVE,"brier_score":brier,"mean_absolute_calibration_error":mae,"buckets":buckets}


def _drift(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows)<10: return {"state":"INSUFFICIENT_DATA","detected":False,"samples":len(rows)}
    cut=max(5,len(rows)//2); old=rows[:-cut]; recent=rows[-cut:]
    old_wr=sum(int(x["won"]) for x in old)/len(old) if old else 0; new_wr=sum(int(x["won"]) for x in recent)/len(recent)
    old_r=sum(float(x["realized_r"]) for x in old)/len(old) if old else 0; new_r=sum(float(x["realized_r"]) for x in recent)/len(recent)
    delta_wr=(new_wr-old_wr)*100; delta_r=new_r-old_r; detected=abs(delta_wr)>=15 or abs(delta_r)>=0.35
    return {"state":"DRIFT_DETECTED" if detected else "STABLE","detected":detected,"recent_samples":len(recent),"win_rate_delta_points":round(delta_wr,2),"expectancy_delta_r":round(delta_r,3)}


def _recommendations(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    recs=[]
    for p in _group(rows,"playbook_id"):
        if p["samples"]>=MIN_PROVISIONAL and (p["win_rate"]<45 or p["average_r"]<0):
            recs.append({"scope":"PLAYBOOK_WEIGHT","subject":p["playbook_id"],"current_value":1.0,"proposed_value":0.85,"reason":"Observed performance is below provisional quality thresholds.","evidence_count":p["samples"],"status":"PENDING_HUMAN_APPROVAL"})
        elif p["samples"]>=MIN_ACTIVE and p["win_rate"]>=65 and p["average_r"]>0.35:
            recs.append({"scope":"PLAYBOOK_WEIGHT","subject":p["playbook_id"],"current_value":1.0,"proposed_value":1.10,"reason":"Observed performance is strong across an active-size sample.","evidence_count":p["samples"],"status":"PENDING_HUMAN_APPROVAL"})
    return recs


def build_continuous_learning(last: Dict[str, Any], history: Any = None, *, before: Optional[str] = None) -> Dict[str, Any]:
    last=last if isinstance(last,dict) else {}; ticker=str(last.get("ticker") or "SPX"); rows=_rows(ticker,before)
    brain=build_institutional_trading_brain(last,history,before=before); regime=build_regime_intelligence(last,history,before=before); playbooks=build_institutional_playbooks(last,history,before=before)
    calibration=_calibration(rows); drift=_drift(rows); recommendations=_recommendations(rows)
    raw=float(brain.get("calibrated_confidence") or brain.get("confidence") or 0)
    applied=raw; adjustment=0.0
    if calibration["state"] in {"PROVISIONAL","ACTIVE"} and rows:
        actual=100*sum(int(x["won"]) for x in rows)/len(rows); predicted=sum(float(x["stated_confidence"]) for x in rows)/len(rows)
        cap=5 if calibration["state"]=="PROVISIONAL" else 10; adjustment=max(-cap,min(cap,(actual-predicted)*0.25)); applied=max(0,min(100,raw+adjustment))
    return {"ok":True,"version":VERSION,"semantic_version":SEMANTIC_VERSION,"schema_version":SCHEMA_VERSION,"evaluated_at":_now(),"ticker":ticker,
      "status":calibration["state"],"calibration":calibration,"confidence":{"raw":round(raw,2),"advisory_calibrated":round(applied,2),"adjustment":round(adjustment,2),"production_confidence_mutated":False},
      "performance":{"by_playbook":_group(rows,"playbook_id"),"by_regime":_group(rows,"regime"),"by_scenario":_group(rows,"forecast_scenario")},"drift":drift,"recommendations":recommendations,
      "current_context":{"playbook":(playbooks.get("selected_playbook") or {}).get("playbook_id"),"regime":regime.get("primary_regime"),"brain_confidence":raw},
      "guardrails":{"read_only_decision_layer":True,"outcome_writes_only":True,"automatic_weight_mutation":False,"automatic_confidence_mutation":False,"human_approval_required":True,"broker_mutation":False,"automatic_execution":False,"existing_kill_switch_authoritative":True,"look_ahead_protected":bool(before)}}
