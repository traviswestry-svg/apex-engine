"""APEX 46 — Adaptive Learning Engine.

Outcome-calibrated, bounded learning for advisory scoring weights. The engine is
shadow-first, auditable, and cannot place or modify orders.
"""
from __future__ import annotations
from .canonical_persistence import connect as canonical_connect

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "46.0.0"
SCHEMA_VERSION = "apex.adaptive_learning.v1"
DEFAULT_DB = os.getenv("APEX_ADAPTIVE_DB", "apex_adaptive_learning.db")
MIN_TRAINING_SAMPLES = int(os.getenv("APEX_ADAPTIVE_MIN_SAMPLES", "30"))
MIN_ACTIVATION_SAMPLES = int(os.getenv("APEX_ADAPTIVE_ACTIVATION_SAMPLES", "100"))
ACTIVATE = os.getenv("APEX_ADAPTIVE_ACTIVATE", "0").strip().lower() in {"1", "true", "yes", "on"}

DEFAULT_WEIGHTS: dict[str, float] = {
    "liquidity": 0.22,
    "order_flow": 0.18,
    "delta": 0.14,
    "auction": 0.12,
    "structure": 0.12,
    "momentum": 0.10,
    "gamma": 0.07,
    "vwap": 0.05,
}


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = canonical_connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS adaptive_outcomes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      observed_at TEXT NOT NULL,
      ticker TEXT NOT NULL,
      direction TEXT NOT NULL,
      confidence REAL NOT NULL,
      won INTEGER NOT NULL,
      realized_return REAL NOT NULL,
      horizon_seconds INTEGER,
      features_json TEXT NOT NULL,
      metadata_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS adaptive_model_state (
      id INTEGER PRIMARY KEY CHECK (id=1),
      updated_at TEXT NOT NULL,
      sample_count INTEGER NOT NULL,
      mode TEXT NOT NULL,
      weights_json TEXT NOT NULL,
      diagnostics_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS adaptive_audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      observed_at TEXT NOT NULL,
      action TEXT NOT NULL,
      detail_json TEXT NOT NULL
    );
    """)
    return conn


def extract_features(snapshot: Mapping[str, Any] | None) -> dict[str, float]:
    s = dict(snapshot or {})
    narrative = s.get("market_narrative") or {}
    breakdown = narrative.get("confidence_breakdown") or []
    by_name = {str(x.get("name", "")).lower().replace(" ", "_"): _num(x.get("score"), 50.0) for x in breakdown if isinstance(x, Mapping)}
    li = s.get("liquidity_intelligence") or {}
    race = li.get("race") or s.get("liquidity_race") or {}
    leader = str(race.get("leader") or "BALANCED").upper()
    liquidity = 50.0 + (_num(race.get("edge_pct"), 0.0) / 2.0) * (1 if leader == "UPPER" else -1 if leader == "LOWER" else 0)
    flow = s.get("flow_intelligence_2") or s.get("flow_intelligence") or {}
    auction = s.get("auction_intelligence") or s.get("auction") or {}
    gamma = s.get("gamma_regime") or {}
    structure = s.get("structure") or {}
    return {
        "liquidity": _clamp(by_name.get("liquidity", liquidity), 0, 100),
        "order_flow": _clamp(by_name.get("order_flow", _num(flow.get("flow_score") or flow.get("order_flow_score"), 50)), 0, 100),
        "delta": _clamp(by_name.get("delta", _num(flow.get("delta_score") or flow.get("cumulative_delta_score"), 50)), 0, 100),
        "auction": _clamp(by_name.get("auction", _num(auction.get("auction_score"), 50)), 0, 100),
        "structure": _clamp(by_name.get("structure", _num(s.get("structure_score") or structure.get("score"), 50)), 0, 100),
        "momentum": _clamp(by_name.get("momentum", _num(s.get("momentum_score"), 50)), 0, 100),
        "gamma": _clamp(by_name.get("gamma", _num(s.get("dealer_score") or gamma.get("score"), 50)), 0, 100),
        "vwap": _clamp(by_name.get("vwap", _num(s.get("vwap_score"), 50)), 0, 100),
    }


def _load_state(path: str | Path = DEFAULT_DB) -> dict[str, Any]:
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM adaptive_model_state WHERE id=1").fetchone()
    if not row:
        return {"sample_count": 0, "mode": "COLD_START", "weights": dict(DEFAULT_WEIGHTS), "diagnostics": {}}
    return {
        "sample_count": int(row["sample_count"]),
        "mode": str(row["mode"]),
        "weights": json.loads(row["weights_json"]),
        "diagnostics": json.loads(row["diagnostics_json"]),
        "updated_at": row["updated_at"],
    }


def record_outcome(event: Mapping[str, Any], path: str | Path = DEFAULT_DB) -> int:
    e = dict(event or {})
    direction = str(e.get("direction") or "NEUTRAL").upper()
    if direction not in {"BULLISH", "BEARISH"}:
        raise ValueError("direction must be BULLISH or BEARISH")
    confidence = _clamp(_num(e.get("confidence"), 50), 0, 100)
    won = bool(e.get("won"))
    realized_return = _num(e.get("realized_return"), 1.0 if won else -1.0)
    features = e.get("features") if isinstance(e.get("features"), Mapping) else extract_features(e.get("snapshot") or e)
    clean_features = {k: _clamp(_num(features.get(k), 50), 0, 100) for k in DEFAULT_WEIGHTS}
    with _connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO adaptive_outcomes (observed_at,ticker,direction,confidence,won,realized_return,horizon_seconds,features_json,metadata_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (str(e.get("observed_at") or _utcnow()), str(e.get("ticker") or "SPX"), direction, confidence, int(won), realized_return,
             int(_num(e.get("horizon_seconds"), 0)) or None, json.dumps(clean_features), json.dumps(e.get("metadata") or {}, default=str)),
        )
        return int(cur.lastrowid)


def recalibrate(path: str | Path = DEFAULT_DB) -> dict[str, Any]:
    with _connect(path) as conn:
        rows = conn.execute("SELECT confidence,won,realized_return,features_json FROM adaptive_outcomes ORDER BY id").fetchall()
    n = len(rows)
    wins = sum(int(r["won"]) for r in rows)
    losses = n - wins
    brier = sum(((float(r["confidence"])/100.0) - int(r["won"])) ** 2 for r in rows) / n if n else None
    diagnostics: dict[str, Any] = {"samples": n, "wins": wins, "losses": losses, "win_rate_pct": round(wins/n*100, 1) if n else None,
                                   "brier_score": round(brier, 4) if brier is not None else None}
    proposed = dict(DEFAULT_WEIGHTS)
    feature_edge: dict[str, float] = {}
    if n >= MIN_TRAINING_SAMPLES and wins >= 8 and losses >= 8:
        raw: dict[str, float] = {}
        for name, default in DEFAULT_WEIGHTS.items():
            signal = 0.0
            denom = 0.0
            for r in rows:
                f = json.loads(r["features_json"])
                centered = (_num(f.get(name), 50) - 50.0) / 50.0
                outcome = 1.0 if int(r["won"]) else -1.0
                magnitude = _clamp(abs(_num(r["realized_return"], 1.0)), 0.25, 3.0)
                signal += centered * outcome * magnitude
                denom += magnitude
            edge = signal / denom if denom else 0.0
            feature_edge[name] = round(edge, 4)
            raw[name] = default * _clamp(1.0 + edge * 0.45, 0.80, 1.20)
        total = sum(raw.values()) or 1.0
        proposed = {k: round(v/total, 6) for k, v in raw.items()}
    diagnostics["feature_edge"] = feature_edge
    mode = "COLD_START" if n < MIN_TRAINING_SAMPLES else "SHADOW_LEARNING" if n < MIN_ACTIVATION_SAMPLES or not ACTIVATE else "ACTIVE_BOUNDED"
    active_weights = proposed if mode == "ACTIVE_BOUNDED" else dict(DEFAULT_WEIGHTS)
    state = {"sample_count": n, "mode": mode, "weights": active_weights, "proposed_weights": proposed, "diagnostics": diagnostics, "updated_at": _utcnow()}
    with _connect(path) as conn:
        conn.execute("INSERT INTO adaptive_model_state (id,updated_at,sample_count,mode,weights_json,diagnostics_json) VALUES (1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,sample_count=excluded.sample_count,mode=excluded.mode,weights_json=excluded.weights_json,diagnostics_json=excluded.diagnostics_json",
                     (state["updated_at"], n, mode, json.dumps(active_weights), json.dumps({**diagnostics, "proposed_weights": proposed})))
        conn.execute("INSERT INTO adaptive_audit_log (observed_at,action,detail_json) VALUES (?,?,?)", (_utcnow(), "RECALIBRATE", json.dumps(state)))
    return state


def evaluate(snapshot: Mapping[str, Any] | None = None, path: str | Path = DEFAULT_DB) -> dict[str, Any]:
    state = _load_state(path)
    features = extract_features(snapshot)
    diagnostics = state.get("diagnostics") or {}
    proposed = diagnostics.get("proposed_weights") or state.get("weights") or DEFAULT_WEIGHTS
    samples = int(state.get("sample_count") or 0)
    remaining = max(0, MIN_TRAINING_SAMPLES - samples)
    mode = str(state.get("mode") or "COLD_START")
    return {
        "ok": True,
        "status": mode,
        "active_weights": state.get("weights") or dict(DEFAULT_WEIGHTS),
        "proposed_weights": proposed,
        "feature_snapshot": features,
        "sample_count": samples,
        "minimum_training_samples": MIN_TRAINING_SAMPLES,
        "activation_samples": MIN_ACTIVATION_SAMPLES,
        "samples_until_training": remaining,
        "calibration": diagnostics,
        "learning_enabled": nbool(ACTIVATE),
        "applied_to_live_scoring": mode == "ACTIVE_BOUNDED",
        "guardrails": {
            "shadow_first": True,
            "minimum_samples": MIN_TRAINING_SAMPLES,
            "minimum_activation_samples": MIN_ACTIVATION_SAMPLES,
            "per_feature_change_limit_pct": 20,
            "execution_authority": False,
        },
        "interpretation": _interpret(mode, samples, remaining, diagnostics),
        "schema_version": SCHEMA_VERSION,
        "engine_version": VERSION,
        "advisory_only": True,
    }


def nbool(v: Any) -> bool:
    return bool(v)


def _interpret(mode: str, samples: int, remaining: int, diagnostics: Mapping[str, Any]) -> str:
    if mode == "COLD_START":
        return f"Adaptive learning is collecting outcomes. {remaining} more graded outcomes are required before weight proposals are trusted."
    if mode == "SHADOW_LEARNING":
        return f"APEX has {samples} graded outcomes and is evaluating bounded weight changes in shadow mode; live scoring remains unchanged."
    return f"Bounded adaptive weights are active from {samples} graded outcomes. All changes remain capped and auditable."


def summary(path: str | Path = DEFAULT_DB) -> dict[str, Any]:
    state = _load_state(path)
    with _connect(path) as conn:
        recent = conn.execute("SELECT observed_at,ticker,direction,confidence,won,realized_return FROM adaptive_outcomes ORDER BY id DESC LIMIT 25").fetchall()
        audits = conn.execute("SELECT observed_at,action,detail_json FROM adaptive_audit_log ORDER BY id DESC LIMIT 10").fetchall()
    return {**state, "recent_outcomes": [dict(r) for r in recent], "recent_audits": [{"observed_at":r["observed_at"],"action":r["action"]} for r in audits],
            "engine_version": VERSION, "schema_version": SCHEMA_VERSION, "advisory_only": True}
