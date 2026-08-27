"""APEX 69.5.2 canonical-persistence observational store for ES tick momentum."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from . import canonical_persistence as persistence
from .tick_momentum import VERSION, initial_state

SCHEMA_VERSION = "apex.tick_momentum.store.v1"
DEFAULT_DB = Path("/data/apex_tick_momentum.db" if Path("/data").exists() else "data/apex_tick_momentum.db")

class TickMomentumStore:
    def __init__(self, path: str | Path = DEFAULT_DB): self.path = Path(path)
    def initialize(self) -> None:
        with persistence.connection(self.path) as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS tick_momentum_state(instrument TEXT PRIMARY KEY, updated_at TEXT, state_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tick_momentum_snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, instrument TEXT NOT NULL, observed_at TEXT NOT NULL, session_date TEXT, horizon INTEGER NOT NULL, state TEXT NOT NULL, raw REAL, alignment_score INTEGER, alignment_state TEXT, payload_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_tick_momentum_history ON tick_momentum_snapshots(instrument, observed_at DESC);
            """)
    def load_state(self, instrument: str = "ES") -> dict[str, Any]:
        self.initialize()
        with persistence.connection(self.path, read_only=True, wal=False, heal=False) as c:
            r=c.execute("SELECT state_json FROM tick_momentum_state WHERE instrument=?",(instrument.upper(),)).fetchone()
        return json.loads(r[0]) if r else initial_state(instrument)
    def save(self, state: dict[str, Any], closed: list[dict[str, Any]]) -> None:
        self.initialize(); inst=str(state.get("instrument") or "ES").upper(); updated=state.get("last_trade_at")
        with persistence.transaction(self.path) as c:
            c.execute("INSERT INTO tick_momentum_state(instrument,updated_at,state_json) VALUES(?,?,?) ON CONFLICT(instrument) DO UPDATE SET updated_at=excluded.updated_at,state_json=excluded.state_json",(inst,updated,json.dumps(state,separators=(',',':'),sort_keys=True)))
            for x in closed:
                c.execute("INSERT INTO tick_momentum_snapshots(instrument,observed_at,session_date,horizon,state,raw,alignment_score,alignment_state,payload_json) VALUES(?,?,?,?,?,?,?,?,?)",(inst,x["observed_at"],x.get("session_date"),int(x["horizon"]),x["state"],x.get("raw"),state["alignment"]["score"],state["alignment"]["state"],json.dumps(x,separators=(',',':'),sort_keys=True)))
    def history(self, instrument: str="ES", limit:int=100) -> list[dict[str,Any]]:
        self.initialize()
        with persistence.connection(self.path,read_only=True,wal=False,heal=False) as c:
            rows=c.execute("SELECT observed_at,session_date,horizon,state,raw,alignment_score,alignment_state FROM tick_momentum_snapshots WHERE instrument=? ORDER BY id DESC LIMIT ?",(instrument.upper(),max(1,min(int(limit),2000)))).fetchall()
        return [dict(r) for r in rows]
    def health(self, instrument: str="ES") -> dict[str,Any]:
        state=self.load_state(instrument); hist=self.history(instrument,1)
        feed=state.get("feed") if isinstance(state.get("feed"),dict) else {}
        tx=int(state.get("transactions_seen",0) or 0)
        status="READY" if tx else str(feed.get("status") or "WAITING_FOR_TRANSACTION_FEED")
        return {"ok":True,"version":VERSION,"schema_version":SCHEMA_VERSION,"instrument":instrument.upper(),"transactions_seen":tx,"last_trade_at":state.get("last_trade_at"),"snapshots_present":bool(hist),"status":status,"feed":feed,"persistence_policy":"CANONICAL_PERSISTENCE_OBSERVATIONAL_STATE"}
