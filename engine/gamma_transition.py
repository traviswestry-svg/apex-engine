"""APEX 69.10.0 Gamma Transition Dynamics.

Temporal derivatives over the existing canonical gamma output. Snapshots are
stored in the existing canonical DB path in one additive observational table;
there is no second gamma engine or outcome ledger.
"""
from __future__ import annotations

import datetime as dt
import json, math, os
from typing import Any, Dict, Mapping, Optional
from .canonical_persistence import connect

VERSION = "69.10.0"
SCHEMA_VERSION = "apex.gamma_transition.v1"
MAX_STALE_SECONDS = 900


def _f(v: Any) -> Optional[float]:
    try:
        x=float(v); return x if math.isfinite(x) else None
    except (TypeError, ValueError): return None


def _iso(v: Any=None) -> str:
    if v: return str(v)
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _db_path() -> str: return os.getenv("DB_PATH", "apex_tracking.db")


def init_db(path: Optional[str]=None) -> bool:
    try:
        with connect(path or _db_path(), timeout=10) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS gamma_observational_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
                observed_at TEXT NOT NULL, source_timestamp TEXT, source TEXT,
                path_version TEXT, net_gex REAL, gamma_flip REAL,
                zero_dte_share REAL, zero_one_dte_share REAL, weekly_gamma_share REAL,
                durability TEXT, capacity_ratio REAL, snapshot_json TEXT NOT NULL)''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_gamma_obs_ticker_time ON gamma_observational_snapshots(ticker, observed_at)")
            c.commit()
        return True
    except Exception: return False


def snapshot_from_gamma(gamma: Mapping[str, Any], *, ticker: str="SPX", source: str="QUANTDATA", observed_at: Optional[str]=None) -> Dict[str, Any]:
    gp = gamma.get("gamma_path") if isinstance(gamma.get("gamma_path"), Mapping) else {}
    gt = gamma.get("gamma_term_structure") if isinstance(gamma.get("gamma_term_structure"), Mapping) else {}
    mc = gt.get("maturity_concentration") if isinstance(gt.get("maturity_concentration"), Mapping) else {}
    return {"ticker": ticker, "observed_at": _iso(observed_at), "source_timestamp": gp.get("source_snapshot_at"),
            "source": source, "path_version": gp.get("path_version"), "net_gex": _f(gamma.get("net_gex")),
            "gamma_flip": _f(gamma.get("active_gamma_flip")), "zero_dte_share": _f(mc.get("zero_dte_gamma_share")),
            "zero_one_dte_share": _f(mc.get("zero_one_dte_gamma_share")), "weekly_gamma_share": _f(mc.get("seven_dte_gamma_share")),
            "durability": mc.get("structure_durability"), "capacity_ratio": _f(gamma.get("capacity_ratio"))}


def _parse(s: Any) -> Optional[dt.datetime]:
    try: return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception: return None


def _prior(path: str, ticker: str, observed: dt.datetime, minutes: int) -> Optional[Dict[str, Any]]:
    target = observed - dt.timedelta(minutes=minutes)
    with connect(path, timeout=10) as c:
        c.row_factory = __import__('sqlite3').Row
        r=c.execute("SELECT * FROM gamma_observational_snapshots WHERE ticker=? AND observed_at<=? ORDER BY observed_at DESC LIMIT 1", (ticker,target.isoformat())).fetchone()
    return dict(r) if r else None


def _delta(cur: Mapping[str, Any], prev: Optional[Mapping[str, Any]], key: str, observed: dt.datetime, minutes: int) -> Optional[float]:
    if not prev: return None
    pt=_parse(prev.get("observed_at")); a,b=_f(cur.get(key)),_f(prev.get(key))
    if pt is None or a is None or b is None: return None
    age=(observed-pt).total_seconds()
    # Reject snapshots too old to represent the requested horizon.
    if age < minutes*60 or age > minutes*60 + MAX_STALE_SECONDS: return None
    return round(a-b, 6)


def compute_transition(current: Mapping[str, Any], *, db_path: Optional[str]=None) -> Dict[str, Any]:
    path=db_path or _db_path(); observed=_parse(current.get("observed_at"))
    base={"status":"UNAVAILABLE","transition_state":"UNAVAILABLE","net_gex_change_5m":None,"net_gex_change_15m":None,"net_gex_change_30m":None,
          "gamma_flip_change":None,"gamma_flip_velocity":None,"zero_dte_share_change":None,"zero_one_dte_share_change":None,
          "weekly_gamma_share_change":None,"durability_change":None,"gamma_path_transition":None,"schema_version":SCHEMA_VERSION,
          "behavioral_authority":False,"execution_authority":False,"automatic_calibration_activation":False,"production_effect":"NONE"}
    if observed is None: return base
    try:
        p5,p15,p30=(_prior(path,str(current.get("ticker") or "SPX"),observed,m) for m in (5,15,30))
    except Exception: return base
    d5=_delta(current,p5,"net_gex",observed,5); d15=_delta(current,p15,"net_gex",observed,15); d30=_delta(current,p30,"net_gex",observed,30)
    flip15=_delta(current,p15,"gamma_flip",observed,15)
    z15=_delta(current,p15,"zero_dte_share",observed,15); zo15=_delta(current,p15,"zero_one_dte_share",observed,15); w15=_delta(current,p15,"weekly_gamma_share",observed,15)
    available=[x for x in (d5,d15,d30,flip15,z15,zo15,w15) if x is not None]
    if not available:
        return {**base,"status":"COLLECTING","transition_state":"INSUFFICIENT_HISTORY"}
    # Scale direction by current absolute GEX to avoid hard-coding provider units.
    ng=_f(current.get("net_gex")); rel15=(d15/abs(ng)) if d15 is not None and ng not in (None,0) else None
    rel5=(d5/abs(ng)) if d5 is not None and ng not in (None,0) else None
    rapid = rel5 is not None and abs(rel5) >= .30
    if rapid: state="RAPID_TRANSITION"
    elif rel15 is not None and rel15 >= .10: state="STRENGTHENING"
    elif rel15 is not None and rel15 <= -.10: state="WEAKENING"
    else: state="STABLE"
    prev=p15 or p5 or p30
    return {**base,"status":"AVAILABLE","transition_state":state,"net_gex_change_5m":d5,"net_gex_change_15m":d15,"net_gex_change_30m":d30,
            "gamma_flip_change":flip15,"gamma_flip_velocity":None if flip15 is None else round(flip15/15.0,6),
            "zero_dte_share_change":z15,"zero_one_dte_share_change":zo15,"weekly_gamma_share_change":w15,
            "durability_change":None if not prev else f"{prev.get('durability') or 'UNKNOWN'}->{current.get('durability') or 'UNKNOWN'}",
            "gamma_path_transition":None if not prev else f"{prev.get('path_version') or 'UNKNOWN'}->{current.get('path_version') or 'UNKNOWN'}"}


def observe_gamma_transition(gamma: Mapping[str, Any], *, ticker: str="SPX", source: str="QUANTDATA", observed_at: Optional[str]=None, db_path: Optional[str]=None) -> Dict[str, Any]:
    path=db_path or _db_path()
    if not init_db(path): return {"status":"UNAVAILABLE","transition_state":"UNAVAILABLE","execution_authority":False,"behavioral_authority":False}
    snap=snapshot_from_gamma(gamma,ticker=ticker,source=source,observed_at=observed_at)
    transition=compute_transition(snap,db_path=path)
    try:
        with connect(path, timeout=10) as c:
            c.execute('''INSERT INTO gamma_observational_snapshots
              (ticker,observed_at,source_timestamp,source,path_version,net_gex,gamma_flip,zero_dte_share,zero_one_dte_share,weekly_gamma_share,durability,capacity_ratio,snapshot_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (snap['ticker'],snap['observed_at'],snap['source_timestamp'],snap['source'],snap['path_version'],snap['net_gex'],snap['gamma_flip'],snap['zero_dte_share'],snap['zero_one_dte_share'],snap['weekly_gamma_share'],snap['durability'],snap['capacity_ratio'],json.dumps(snap,sort_keys=True)))
            c.commit()
    except Exception: pass
    return transition
