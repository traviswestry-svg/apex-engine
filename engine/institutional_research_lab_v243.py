"""APEX 24.3 - Strategy Research Laboratory.

An institutional research environment that extends the existing APEX 15.5
``institutional_research_lab`` (governed, immutable candidate/run/attribution
registry) with:

  * Performance analytics: win rate, expectancy, profit factor, average R, max
    drawdown, and regime / strategy-family / position-sizing breakdowns.
  * Experiment tracking: strategy revisions, parameter experiments, before/after
    comparisons, notes, and immutable version history.
  * Research dashboards: strategy ranking, regime comparison, equity curves,
    performance summaries, and experiment history.

Reuse, not duplication: candidate/run/compare/attribution/readiness all delegate
to ``institutional_research_lab``. This module adds the analytics and experiment
layers on top.

Safety: everything here is offline research only. Experiments NEVER alter
production settings; there is no path from this module to Configuration
Governance production values, order placement, or automatic promotion.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any, Mapping, Optional, Sequence

from . import institutional_governance as gov
from . import institutional_research_lab as lab

VERSION = "24.3.0_STRATEGY_RESEARCH_LABORATORY"
SCHEMA_VERSION = "apex.research_lab_v243.v1"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def _load(v: Any, default: Any = None) -> Any:
    if v in (None, ""):
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def _conn():
    c = sqlite3.connect(gov.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default  # NaN guard
    except Exception:
        return default


def init_db() -> dict[str, Any]:
    lab.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS apex_research_experiments_v243(
          experiment_id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          strategy TEXT NOT NULL,
          hypothesis TEXT NOT NULL,
          baseline_params_json TEXT NOT NULL,
          current_version INTEGER NOT NULL,
          notes TEXT,
          schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS apex_research_experiment_versions_v243(
          version_id TEXT PRIMARY KEY,
          experiment_id TEXT NOT NULL,
          version_no INTEGER NOT NULL,
          params_json TEXT NOT NULL,
          notes TEXT,
          before_metrics_json TEXT NOT NULL,
          after_metrics_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(experiment_id) REFERENCES apex_research_experiments_v243(experiment_id),
          UNIQUE(experiment_id, version_no));
        CREATE INDEX IF NOT EXISTS idx_research_v243_versions ON apex_research_experiment_versions_v243(experiment_id, version_no);
        """)
    return {"ok": True, "schema_version": SCHEMA_VERSION, "build_version": VERSION}


# ---------------------------------------------------------------------------
# Performance analytics (pure, deterministic)
# ---------------------------------------------------------------------------

def _trade_pnl(t: Mapping[str, Any]) -> float:
    if "pnl" in t and t["pnl"] is not None:
        return _num(t["pnl"])
    # Derive from R multiple and risk if pnl not supplied.
    return _num(t.get("r_multiple")) * _num(t.get("risk_per_unit"), 1.0)


def _trade_is_win(t: Mapping[str, Any]) -> bool:
    if "win" in t and t["win"] is not None:
        return bool(t["win"])
    return _trade_pnl(t) > 0


def _core_metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"sample": 0, "win_rate": 0.0, "expectancy": 0.0, "profit_factor": 0.0,
                "average_r": 0.0, "max_drawdown": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
                "net_pnl": 0.0}
    pnls = [_trade_pnl(t) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = round(sum(wins), 4)
    gross_loss = round(abs(sum(losses)), 4)
    win_rate = round(100.0 * len(wins) / n, 2)
    expectancy = round(sum(pnls) / n, 4)
    r_values = [_num(t.get("r_multiple")) for t in trades if t.get("r_multiple") is not None]
    average_r = round(sum(r_values) / len(r_values), 4) if r_values else 0.0
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0)
    # Max drawdown on cumulative equity.
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "sample": n, "win_rate": win_rate, "expectancy": expectancy,
        "profit_factor": profit_factor if profit_factor != float("inf") else "INF",
        "average_r": average_r, "max_drawdown": round(max_dd, 4),
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "net_pnl": round(sum(pnls), 4),
    }


def _group_metrics(trades: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list] = {}
    for t in trades:
        g = str(t.get(key) or "UNSPECIFIED")
        groups.setdefault(g, []).append(t)
    return {g: _core_metrics(ts) for g, ts in sorted(groups.items())}


def performance_analytics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Full performance analytics over a list of trade records."""
    trades = [t for t in trades if isinstance(t, Mapping)]
    return {
        "ok": True, "status": "READY", "version": VERSION,
        "overall": _core_metrics(trades),
        "by_regime": _group_metrics(trades, "regime"),
        "by_strategy_family": _group_metrics(trades, "strategy_family"),
        "by_position_sizing": _group_metrics(trades, "size_bucket"),
        "production_effect": "NONE",
    }


def equity_curve(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    trades = [t for t in trades if isinstance(t, Mapping)]
    points = []
    equity = 0.0
    for i, t in enumerate(trades):
        equity += _trade_pnl(t)
        points.append({"index": i, "equity": round(equity, 4),
                       "label": str(t.get("id") or t.get("trade_id") or i)})
    return {"ok": True, "points": points, "final_equity": round(equity, 4),
            "sample": len(points), "production_effect": "NONE"}


def rank_strategies(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Rank strategies by expectancy then profit factor. Accepts entries of
    ``{strategy, trades}`` or ``{strategy, metrics}``."""
    ranked = []
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        name = str(e.get("strategy") or e.get("name") or "STRATEGY")
        if "metrics" in e and isinstance(e["metrics"], Mapping):
            m = dict(e["metrics"])
        else:
            m = _core_metrics(e.get("trades") or [])
        pf = m.get("profit_factor")
        pf_sort = 1e9 if pf == "INF" else _num(pf)
        ranked.append({"strategy": name, "expectancy": _num(m.get("expectancy")),
                       "profit_factor": pf, "win_rate": _num(m.get("win_rate")),
                       "average_r": _num(m.get("average_r")),
                       "max_drawdown": _num(m.get("max_drawdown")),
                       "sample": int(_num(m.get("sample"))), "_pf": pf_sort})
    ranked.sort(key=lambda r: (r["expectancy"], r["_pf"]), reverse=True)
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
        r.pop("_pf", None)
    return {"ok": True, "ranking": ranked, "count": len(ranked), "production_effect": "NONE"}


def regime_comparison(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    trades = [t for t in trades if isinstance(t, Mapping)]
    return {"ok": True, "status": "READY", "by_regime": _group_metrics(trades, "regime"),
            "production_effect": "NONE"}


# ---------------------------------------------------------------------------
# Experiment tracking (immutable version history; never alters production)
# ---------------------------------------------------------------------------

def create_experiment(*, name: str, strategy: str, hypothesis: str,
                      baseline_params: Optional[Mapping[str, Any]] = None,
                      notes: str = "", actor: str = "SYSTEM") -> dict[str, Any]:
    init_db()
    baseline_params = dict(baseline_params or {})
    with _conn() as c:
        row = c.execute("SELECT * FROM apex_research_experiments_v243 WHERE name=?", (name,)).fetchone()
        if row:
            return {"ok": True, "status": "EXISTS", "created": False,
                    "experiment_id": row["experiment_id"], "production_settings_modified": False}
    eid = str(uuid.uuid4())
    vid = str(uuid.uuid4())
    created = _now()
    payload = {"name": name, "strategy": strategy, "hypothesis": hypothesis,
               "baseline_params": baseline_params}
    ih = hashlib.sha256(_json(payload).encode()).hexdigest()
    with _conn() as c:
        c.execute("INSERT INTO apex_research_experiments_v243 VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (eid, name, strategy, hypothesis, _json(baseline_params), 1, notes,
                   SCHEMA_VERSION, VERSION, ih, created))
        c.execute("INSERT INTO apex_research_experiment_versions_v243 VALUES(?,?,?,?,?,?,?,?,?)",
                  (vid, eid, 1, _json(baseline_params), notes or "baseline",
                   _json({}), _json({}),
                   hashlib.sha256(_json({"v": 1, "params": baseline_params}).encode()).hexdigest(),
                   created))
    gov.audit("CREATE_RESEARCH_EXPERIMENT", "research_experiment_v243", eid,
              new={"name": name, "strategy": strategy}, actor=actor,
              explanation="Offline research experiment created; no production settings changed")
    return {"ok": True, "status": "CREATED", "created": True, "experiment_id": eid,
            "name": name, "strategy": strategy, "current_version": 1,
            "production_settings_modified": False, "production_effect": "NONE"}


def add_revision(*, experiment_id: str, params: Mapping[str, Any], notes: str = "",
                 before_metrics: Optional[Mapping[str, Any]] = None,
                 after_metrics: Optional[Mapping[str, Any]] = None,
                 actor: str = "SYSTEM") -> dict[str, Any]:
    init_db()
    with _conn() as c:
        exp = c.execute("SELECT * FROM apex_research_experiments_v243 WHERE experiment_id=?",
                        (experiment_id,)).fetchone()
        if not exp:
            return {"ok": False, "status": "EXPERIMENT_NOT_FOUND"}
        next_version = int(exp["current_version"]) + 1
        vid = str(uuid.uuid4())
        created = _now()
        before = dict(before_metrics or {})
        after = dict(after_metrics or {})
        ih = hashlib.sha256(_json({"v": next_version, "params": dict(params)}).encode()).hexdigest()
        c.execute("INSERT INTO apex_research_experiment_versions_v243 VALUES(?,?,?,?,?,?,?,?,?)",
                  (vid, experiment_id, next_version, _json(dict(params)), notes,
                   _json(before), _json(after), ih, created))
        c.execute("UPDATE apex_research_experiments_v243 SET current_version=? WHERE experiment_id=?",
                  (next_version, experiment_id))
    gov.audit("ADD_RESEARCH_EXPERIMENT_REVISION", "research_experiment_v243", experiment_id,
              new={"version": next_version}, actor=actor,
              explanation="Offline experiment revision; no production settings changed")
    comparison = _before_after(before, after)
    return {"ok": True, "status": "CREATED", "experiment_id": experiment_id,
            "version_no": next_version, "before_after": comparison,
            "production_settings_modified": False, "production_effect": "NONE"}


def _before_after(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    keys = sorted(set(before) | set(after))
    delta = {}
    for k in keys:
        b, a = before.get(k), after.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            delta[k] = round(float(a) - float(b), 4)
    return {"before": dict(before), "after": dict(after), "delta": delta}


def experiment(experiment_id: str) -> dict[str, Any]:
    init_db()
    with _conn() as c:
        exp = c.execute("SELECT * FROM apex_research_experiments_v243 WHERE experiment_id=? OR name=?",
                        (experiment_id, experiment_id)).fetchone()
        if not exp:
            return {"ok": False, "status": "NOT_FOUND"}
        versions = c.execute("SELECT version_no, params_json, notes, before_metrics_json, "
                             "after_metrics_json, created_at FROM apex_research_experiment_versions_v243 "
                             "WHERE experiment_id=? ORDER BY version_no ASC", (exp["experiment_id"],)).fetchall()
    history = [{"version_no": v["version_no"], "params": _load(v["params_json"], {}),
                "notes": v["notes"], "before_metrics": _load(v["before_metrics_json"], {}),
                "after_metrics": _load(v["after_metrics_json"], {}), "created_at": v["created_at"]}
               for v in versions]
    return {"ok": True, "status": "READY", "experiment_id": exp["experiment_id"],
            "name": exp["name"], "strategy": exp["strategy"], "hypothesis": exp["hypothesis"],
            "current_version": exp["current_version"], "version_history": history,
            "production_settings_modified": False, "production_effect": "NONE"}


def experiments(limit: int = 100) -> dict[str, Any]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT experiment_id, name, strategy, hypothesis, current_version, "
                         "created_at FROM apex_research_experiments_v243 ORDER BY created_at DESC "
                         "LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
    return {"ok": True, "experiments": [dict(r) for r in rows], "count": len(rows),
            "production_effect": "NONE"}


# ---------------------------------------------------------------------------
# Dashboards + status
# ---------------------------------------------------------------------------

def strategies() -> dict[str, Any]:
    """Strategy ranking built from the immutable lab candidates + runs."""
    init_db()
    cands = lab.candidates(1000)
    ids = [c["candidate_id"] for c in cands]
    comparison = lab.compare(ids) if ids else {"comparison": [], "winner_candidate_id": None}
    return {"ok": True, "status": "READY", "version": VERSION,
            "candidates": cands, "ranking": comparison["comparison"],
            "winner_candidate_id": comparison.get("winner_candidate_id"),
            "count": len(cands), "production_effect": "NONE"}


def performance() -> dict[str, Any]:
    """Performance summary aggregated across each candidate's immutable runs.

    Per-trade analytics (win rate / expectancy / profit factor / R / drawdown and
    regime / family / sizing breakdowns) are available via ``performance_analytics``
    with a supplied trade list.
    """
    init_db()
    entries = []
    for c in lab.candidates(1000):
        rs = lab.runs(c["candidate_id"], 1000)
        if not rs:
            continue
        m = len(rs)

        def avg(k, rs=rs, m=m):
            return round(sum(_num(x["metrics"].get(k)) for x in rs) / m, 4)
        entries.append({"strategy": c["name"], "metrics": {
            "expectancy": avg("expectancy"), "win_rate": avg("win_rate"),
            "profit_factor": avg("profit_factor"), "average_r": avg("average_r"),
            "max_drawdown": avg("max_drawdown"), "sample": m}})
    ranking = rank_strategies(entries)
    return {"ok": True, "status": "READY", "version": VERSION,
            "strategies": ranking["ranking"], "strategy_count": len(entries),
            "production_effect": "NONE"}


def research_dashboard() -> dict[str, Any]:
    init_db()
    return {"ok": True, "status": "READY", "version": VERSION,
            "candidates": lab.candidates(50),
            "recent_runs": lab.runs(None, 50),
            "attributions": lab.attributions(25),
            "experiments": experiments(50)["experiments"],
            "safety": status(),
            "production_effect": "NONE"}


def status() -> dict[str, Any]:
    init_db()
    with _conn() as c:
        experiment_count = c.execute("SELECT COUNT(*) n FROM apex_research_experiments_v243").fetchone()["n"]
        revision_count = c.execute("SELECT COUNT(*) n FROM apex_research_experiment_versions_v243").fetchone()["n"]
    base = lab.status()
    return {
        "status": "READY", "engine": "STRATEGY_RESEARCH_LABORATORY",
        "version": VERSION, "schema_version": SCHEMA_VERSION,
        "research_lab_base": base,
        "candidate_count": base.get("research_candidates", 0),
        "run_count": base.get("research_runs", 0),
        "experiment_count": experiment_count,
        "experiment_revision_count": revision_count,
        "offline_research_only": True,
        "production_settings_mutation_enabled": False,
        "automatic_promotion_enabled": False,
        "broker_order_submission_enabled": False,
        "production_effect": "NONE",
    }
