"""APEX 13 Sprint 7: governed offline weight optimization and shadow evaluation.

Research-only. Never mutates production policy or executes trades.
"""
from __future__ import annotations
import datetime as dt, hashlib, itertools, json, math, os, sqlite3, uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import institutional_governance as gov

VERSION = "13.0.7"
SCHEMA_VERSION = 1
FEATURES = ("confidence", "conviction")
DEFAULT_WEIGHTS = {"confidence": 0.5, "conviction": 0.5}
MIN_ROWS = int(os.getenv("APEX_OPTIMIZER_MIN_ROWS", "30"))


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

def _load(value: Any, default: Any = None) -> Any:
    try:
        return json.loads(value) if value not in (None, "") else ({} if default is None else default)
    except Exception:
        return {} if default is None else default

def _conn():
    c = sqlite3.connect(gov.DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db() -> Dict[str, Any]:
    gov.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS weight_optimization_runs(
          run_id TEXT PRIMARY KEY, candidate_id TEXT, created_at TEXT NOT NULL, actor TEXT NOT NULL,
          dataset_hash TEXT NOT NULL, feature_schema TEXT NOT NULL, search_space_json TEXT NOT NULL,
          split_manifest_json TEXT NOT NULL, baseline_json TEXT NOT NULL, selected_json TEXT NOT NULL,
          validation_json TEXT NOT NULL, test_json TEXT NOT NULL, limitations_json TEXT NOT NULL,
          status TEXT NOT NULL, integrity_hash TEXT NOT NULL, production_effect TEXT NOT NULL DEFAULT 'NONE');
        CREATE INDEX IF NOT EXISTS idx_weight_runs_time ON weight_optimization_runs(created_at);
        CREATE TABLE IF NOT EXISTS shadow_scorecards(
          scorecard_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, created_at TEXT NOT NULL,
          observation_count INTEGER NOT NULL, baseline_summary_json TEXT NOT NULL,
          candidate_summary_json TEXT NOT NULL, comparison_json TEXT NOT NULL,
          status TEXT NOT NULL, integrity_hash TEXT NOT NULL, production_effect TEXT NOT NULL DEFAULT 'NONE');
        CREATE INDEX IF NOT EXISTS idx_shadow_scorecard_candidate ON shadow_scorecards(candidate_id,created_at);
        """)
    return {"ok": True, "schema_version": SCHEMA_VERSION, "db_path": gov.DB_PATH}

def _eligible_rows() -> List[Dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = c.execute("""SELECT recommendation_id, graded_at, outcome_label, realized_pnl, realized_r,
            family, regime, confidence, conviction, consensus_grade, data_quality
            FROM graded_outcomes
            WHERE data_quality IN ('GOOD','VERIFIED')
              AND confidence IS NOT NULL AND conviction IS NOT NULL
            ORDER BY graded_at, recommendation_id""").fetchall()
    out = []
    positive = {"WIN", "PROFIT", "SUCCESS", "CORRECT", "TARGET_HIT"}
    negative = {"LOSS", "FAIL", "FAILED", "INCORRECT", "STOPPED", "STOP_HIT"}
    for r in rows:
        d = dict(r)
        label = str(d["outcome_label"] or "").upper()
        if label in positive: y = 1
        elif label in negative: y = 0
        elif d["realized_pnl"] is not None: y = 1 if float(d["realized_pnl"]) > 0 else 0
        elif d["realized_r"] is not None: y = 1 if float(d["realized_r"]) > 0 else 0
        else: continue
        d["target"] = y
        d["confidence"] = max(0.0, min(100.0, float(d["confidence"]))) / 100.0
        d["conviction"] = max(0.0, min(100.0, float(d["conviction"]))) / 100.0
        out.append(d)
    return out

def _dataset_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    body = [{k: r.get(k) for k in ("recommendation_id","graded_at","outcome_label","confidence","conviction","target","data_quality")} for r in rows]
    return hashlib.sha256(_json(body).encode()).hexdigest()

def _split(rows: Sequence[Mapping[str, Any]]) -> Tuple[List, List, List, Dict[str, Any]]:
    n = len(rows)
    train_end = max(1, int(n * 0.60))
    val_end = max(train_end + 1, int(n * 0.80)) if n >= 3 else n
    val_end = min(val_end, n)
    train, val, test = list(rows[:train_end]), list(rows[train_end:val_end]), list(rows[val_end:])
    manifest = {
        "method": "CHRONOLOGICAL_60_20_20",
        "look_ahead_protection": True,
        "train": {"count": len(train), "start": train[0]["graded_at"] if train else None, "end": train[-1]["graded_at"] if train else None},
        "validation": {"count": len(val), "start": val[0]["graded_at"] if val else None, "end": val[-1]["graded_at"] if val else None},
        "test": {"count": len(test), "start": test[0]["graded_at"] if test else None, "end": test[-1]["graded_at"] if test else None},
    }
    return train, val, test, manifest

def _metrics(rows: Sequence[Mapping[str, Any]], weights: Mapping[str, float]) -> Dict[str, Any]:
    if not rows:
        return {"sample_size": 0, "brier_score": None, "log_loss": None, "accuracy_at_0_5": None, "mean_score": None}
    probs, targets = [], []
    for r in rows:
        p = sum(float(weights.get(f, 0.0)) * float(r[f]) for f in FEATURES)
        p = max(1e-6, min(1 - 1e-6, p))
        probs.append(p); targets.append(int(r["target"]))
    brier = sum((p-y)**2 for p,y in zip(probs, targets)) / len(rows)
    logloss = -sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(probs, targets)) / len(rows)
    acc = sum((p >= .5) == bool(y) for p,y in zip(probs, targets)) / len(rows)
    return {"sample_size": len(rows), "brier_score": round(brier, 8), "log_loss": round(logloss, 8), "accuracy_at_0_5": round(acc, 8), "mean_score": round(sum(probs)/len(probs), 8)}

def _search_space(step: float = 0.1) -> List[Dict[str, float]]:
    step = max(0.05, min(0.5, float(step)))
    count = int(round(1.0 / step))
    vals = [round(i / count, 6) for i in range(count + 1)]
    return [{"confidence": v, "conviction": round(1-v, 6)} for v in vals]

def run_optimization(*, actor: str = "SYSTEM", step: float = 0.1, create_candidate: bool = True) -> Dict[str, Any]:
    rows = _eligible_rows(); dataset_hash = _dataset_hash(rows)
    if len(rows) < MIN_ROWS:
        return {"ok": False, "status": "INSUFFICIENT_HISTORY", "sample_size": len(rows), "minimum_required": MIN_ROWS, "dataset_hash": dataset_hash, "production_effect": "NONE"}
    train, val, test, manifest = _split(rows)
    if not train or not val or not test:
        return {"ok": False, "status": "INSUFFICIENT_HISTORY", "error": "chronological train/validation/test split unavailable", "production_effect": "NONE"}
    space = _search_space(step)
    scored = [(w, _metrics(train, w), _metrics(val, w)) for w in space]
    scored.sort(key=lambda x: (x[2]["brier_score"], x[2]["log_loss"], -x[2]["accuracy_at_0_5"], x[0]["confidence"]))
    selected, train_metrics, val_metrics = scored[0]
    baseline = {"weights": DEFAULT_WEIGHTS, "train": _metrics(train, DEFAULT_WEIGHTS), "validation": _metrics(val, DEFAULT_WEIGHTS), "test": _metrics(test, DEFAULT_WEIGHTS)}
    candidate_result = {"weights": selected, "train": train_metrics, "validation": val_metrics, "test": _metrics(test, selected)}
    comparison = {
        "validation_brier_delta": round(candidate_result["validation"]["brier_score"] - baseline["validation"]["brier_score"], 8),
        "test_brier_delta": round(candidate_result["test"]["brier_score"] - baseline["test"]["brier_score"], 8),
        "test_accuracy_delta": round(candidate_result["test"]["accuracy_at_0_5"] - baseline["test"]["accuracy_at_0_5"], 8),
        "candidate_better_on_holdout_brier": candidate_result["test"]["brier_score"] < baseline["test"]["brier_score"],
    }
    candidate_id = None
    evaluation_id = None
    if create_candidate:
        reg = gov.register_candidate("OFFLINE_WEIGHT_OPTIMIZATION", {"weights": selected, "feature_schema": "apex.weight.features.v1"}, dataset_hash=dataset_hash, baseline_version="production-current", metrics={"baseline": baseline, "candidate": candidate_result, "comparison": comparison}, limitations=["Offline historical evaluation only", "No causal claim", "No production effect"], actor=actor)
        candidate_id = reg.get("candidate_id")
        ev = gov.record_offline_evaluation(candidate_id, {
            "dataset_hash": dataset_hash,
            "methodology": {"look_ahead_guard": True, "walk_forward": True, "selection_metric": "validation_brier_score", "holdout_touched_once": True},
            "splits": manifest,
            "baseline_metrics": baseline,
            "candidate_metrics": candidate_result,
            "comparison": comparison,
            "limitations": ["Historical evidence may not represent future regimes", "No production effect"]
        }, actor=actor)
        evaluation_id = ev.get("evaluation_id")
    payload = {"dataset_hash": dataset_hash, "feature_schema": "apex.weight.features.v1", "search_space": space, "split_manifest": manifest, "baseline": baseline, "selected": candidate_result, "comparison": comparison, "limitations": ["Historical evidence may not represent future regimes", "Weights are evaluated offline only", "Human approval is required for shadow mode"], "candidate_id": candidate_id, "evaluation_id": evaluation_id}
    integrity = hashlib.sha256(_json(payload).encode()).hexdigest(); run_id = str(uuid.uuid4())
    with _conn() as c:
        c.execute("INSERT INTO weight_optimization_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id,candidate_id,_now(),actor,dataset_hash,"apex.weight.features.v1",_json(space),_json(manifest),_json(baseline),_json(candidate_result),_json(val_metrics),_json(candidate_result["test"]),_json(payload["limitations"]),"READY_FOR_REVIEW",integrity,"NONE"))
    gov.audit("OFFLINE_WEIGHT_OPTIMIZATION", "optimization_run", run_id, new={"candidate_id":candidate_id,"dataset_hash":dataset_hash,"comparison":comparison}, explanation="Research-only chronological optimization completed", actor=actor)
    return {"ok": True, "status": "READY_FOR_REVIEW", "run_id": run_id, "candidate_id": candidate_id, "integrity_hash": integrity, **payload, "production_effect": "NONE"}

def runs(limit: int = 100) -> List[Dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM weight_optimization_runs ORDER BY created_at DESC LIMIT ?", (max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r)
        for key in ("search_space_json","split_manifest_json","baseline_json","selected_json","validation_json","test_json","limitations_json"):
            d[key[:-5]] = _load(d.pop(key))
        out.append(d)
    return out

def build_shadow_scorecard(candidate_id: str) -> Dict[str, Any]:
    observations = gov.shadows(candidate_id, 500)
    if not observations:
        return {"ok": False, "status": "COLLECTING", "candidate_id": candidate_id, "observation_count": 0, "production_effect": "NONE"}
    base_scores=[]; cand_scores=[]; agreements=0
    for o in observations:
        p=o.get("production") or {}; c=o.get("candidate") or {}
        ps=p.get("score", p.get("confidence")); cs=c.get("score", c.get("confidence"))
        if isinstance(ps,(int,float)) and isinstance(cs,(int,float)):
            base_scores.append(float(ps)); cand_scores.append(float(cs)); agreements += int((float(ps)>=50)==(float(cs)>=50))
    n=len(observations)
    baseline={"mean_score": round(sum(base_scores)/len(base_scores),6) if base_scores else None,"scored_observations":len(base_scores)}
    candidate={"mean_score": round(sum(cand_scores)/len(cand_scores),6) if cand_scores else None,"scored_observations":len(cand_scores)}
    comparison={"decision_agreement_rate": round(agreements/len(base_scores),6) if base_scores else None,"mean_score_delta": round(candidate["mean_score"]-baseline["mean_score"],6) if base_scores else None,"outcome_performance_available":False}
    payload={"candidate_id":candidate_id,"observation_count":n,"baseline":baseline,"candidate":candidate,"comparison":comparison}
    integrity=hashlib.sha256(_json(payload).encode()).hexdigest(); sid=str(uuid.uuid4())
    with _conn() as c:
        c.execute("INSERT INTO shadow_scorecards VALUES(?,?,?,?,?,?,?,?,?,?)",(sid,candidate_id,_now(),n,_json(baseline),_json(candidate),_json(comparison),"SHADOW_ONLY",integrity,"NONE"))
    gov.audit("SHADOW_SCORECARD", "model_candidate", candidate_id, new={"scorecard_id":sid,"observation_count":n}, explanation="Descriptive shadow scorecard generated; no production effect")
    return {"ok":True,"status":"SHADOW_ONLY","scorecard_id":sid,"integrity_hash":integrity,**payload,"production_effect":"NONE"}

def shadow_scorecards(candidate_id: Optional[str]=None, limit:int=100) -> List[Dict[str,Any]]:
    init_db()
    with _conn() as c:
        rows=c.execute("SELECT * FROM shadow_scorecards WHERE candidate_id=? ORDER BY created_at DESC LIMIT ?",(candidate_id,max(1,min(limit,500)))).fetchall() if candidate_id else c.execute("SELECT * FROM shadow_scorecards ORDER BY created_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r)
        for key in ("baseline_summary_json","candidate_summary_json","comparison_json"):
            d[key[:-5]]=_load(d.pop(key))
        out.append(d)
    return out

def status() -> Dict[str,Any]:
    rows=_eligible_rows(); rs=runs(10); cards=shadow_scorecards(limit=10)
    state="READY_FOR_OFFLINE_RESEARCH" if len(rows)>=MIN_ROWS else ("INSUFFICIENT_HISTORY" if rows else "COLLECTING")
    return {"schema_version":"apex.offline.optimization.status.v1","status":state,"eligible_rows":len(rows),"minimum_required":MIN_ROWS,"run_count":len(rs),"shadow_scorecard_count":len(cards),"automatic_production_promotion":False,"production_effect":"NONE","build_version":VERSION}
