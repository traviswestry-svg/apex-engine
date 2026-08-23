"""APEX 68.8.0 — bounded market-microstructure persistence.

Stores normalized ES L2/MBO observations, never aggregate-bar proxies.  The
store is intentionally provider-neutral so a licensed depth bridge can publish
exchange data without coupling the APEX decision layer to a vendor SDK.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping

VERSION = "68.8.0"
SCHEMA_VERSION = "apex.market_microstructure.store.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db_path() -> str:
    configured = (os.getenv("MICROSTRUCTURE_DB_PATH") or "").strip()
    if configured:
        return configured
    data_dir = Path(os.getenv("APEX_DATA_DIR") or "data")
    return str(data_dir / "market_microstructure.sqlite3")


class MicrostructureStore:
    def __init__(self, path: str | None = None, *, max_snapshots: int | None = None, max_age_minutes: int | None = None):
        self.path = path or _default_db_path()
        self.max_snapshots = max(100, int(max_snapshots or os.getenv("MICROSTRUCTURE_MAX_SNAPSHOTS", "12000")))
        self.max_age_minutes = max(15, int(max_age_minutes or os.getenv("MICROSTRUCTURE_MAX_AGE_MINUTES", "480")))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=5.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    def _init(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS microstructure_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    source TEXT NOT NULL,
                    feed_quality TEXT NOT NULL,
                    sequence_id TEXT,
                    best_bid REAL,
                    best_ask REAL,
                    bid_depth REAL,
                    ask_depth REAL,
                    depth_imbalance REAL,
                    aggressive_buy_volume REAL,
                    aggressive_sell_volume REAL,
                    delta REAL,
                    true_delta_available INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_microstructure_obs_inst_time
                    ON microstructure_observations(instrument, observed_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_microstructure_obs_received
                    ON microstructure_observations(received_at DESC, id DESC);
                """
            )

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)

    @staticmethod
    def _load(raw: str | None) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def latest_payload(self, instrument: str = "ES") -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM microstructure_observations WHERE instrument=? ORDER BY observed_at DESC,id DESC LIMIT 1",
                (instrument.upper(),),
            ).fetchone()
        return self._load(row["payload_json"]) if row else None

    def latest_analysis(self, instrument: str = "ES") -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT analysis_json FROM microstructure_observations WHERE instrument=? ORDER BY observed_at DESC,id DESC LIMIT 1",
                (instrument.upper(),),
            ).fetchone()
        return self._load(row["analysis_json"]) if row else None

    def append(self, payload: Mapping[str, Any], analysis: Mapping[str, Any]) -> int:
        instrument = str(payload.get("instrument") or analysis.get("instrument") or "ES").upper()
        source = str(payload.get("source") or analysis.get("source") or "UNSPECIFIED")
        feed_quality = str(payload.get("feed_quality") or "L2").upper()
        observed_at = str(payload.get("observed_at") or analysis.get("observed_at") or _now())
        sequence_id = payload.get("sequence_id")
        book = analysis.get("book") if isinstance(analysis.get("book"), Mapping) else {}
        execution = analysis.get("execution") if isinstance(analysis.get("execution"), Mapping) else {}
        best_bid = book.get("best_bid") if isinstance(book.get("best_bid"), Mapping) else {}
        best_ask = book.get("best_ask") if isinstance(book.get("best_ask"), Mapping) else {}
        with self._connect() as con:
            cur = con.execute(
                """INSERT INTO microstructure_observations (
                    observed_at,received_at,instrument,source,feed_quality,sequence_id,
                    best_bid,best_ask,bid_depth,ask_depth,depth_imbalance,
                    aggressive_buy_volume,aggressive_sell_volume,delta,true_delta_available,
                    payload_json,analysis_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    observed_at, _now(), instrument, source, feed_quality,
                    None if sequence_id is None else str(sequence_id),
                    best_bid.get("price"), best_ask.get("price"), book.get("bid_depth"), book.get("ask_depth"),
                    book.get("depth_imbalance"), execution.get("aggressive_buy_volume"), execution.get("aggressive_sell_volume"),
                    execution.get("delta"), 1 if execution.get("true_delta_available") else 0,
                    self._dump(dict(payload)), self._dump(dict(analysis)),
                ),
            )
            row_id = int(cur.lastrowid)
            self._prune(con, instrument)
            return row_id

    def _prune(self, con: sqlite3.Connection, instrument: str) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=self.max_age_minutes)).isoformat()
        con.execute("DELETE FROM microstructure_observations WHERE observed_at < ?", (cutoff,))
        con.execute(
            """DELETE FROM microstructure_observations WHERE instrument=? AND id NOT IN (
                 SELECT id FROM microstructure_observations WHERE instrument=? ORDER BY observed_at DESC,id DESC LIMIT ?
               )""",
            (instrument, instrument, self.max_snapshots),
        )

    def history(self, instrument: str = "ES", *, limit: int = 120) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 2000)
        with self._connect() as con:
            rows = con.execute(
                """SELECT id,observed_at,received_at,instrument,source,feed_quality,sequence_id,
                          best_bid,best_ask,bid_depth,ask_depth,depth_imbalance,
                          aggressive_buy_volume,aggressive_sell_volume,delta,true_delta_available
                   FROM microstructure_observations WHERE instrument=?
                   ORDER BY observed_at DESC,id DESC LIMIT ?""",
                (instrument.upper(), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def rolling_cvd(self, instrument: str = "ES", *, limit: int = 600) -> dict[str, Any]:
        rows = list(reversed(self.history(instrument, limit=limit)))
        cvd = 0.0
        points: list[dict[str, Any]] = []
        all_classified = True
        eligible = 0
        for row in rows:
            delta = row.get("delta")
            if not row.get("true_delta_available") or delta is None:
                all_classified = False
                continue
            eligible += 1
            cvd += float(delta)
            points.append({"observed_at": row["observed_at"], "delta": float(delta), "cvd": round(cvd, 4)})
        return {
            "available": eligible > 0,
            "authoritative_for_window": bool(eligible > 0 and all_classified and eligible == len(rows)),
            "observations": len(rows),
            "eligible_observations": eligible,
            "cvd": round(cvd, 4) if eligible else None,
            "points": points,
        }

    def heatmap(self, instrument: str = "ES", *, limit: int = 240, min_persistence: float = 0.05) -> dict[str, Any]:
        limit = min(max(int(limit), 1), 2000)
        with self._connect() as con:
            rows = con.execute(
                "SELECT observed_at,payload_json FROM microstructure_observations WHERE instrument=? ORDER BY observed_at DESC,id DESC LIMIT ?",
                (instrument.upper(), limit),
            ).fetchall()
        counts: dict[tuple[str, float], dict[str, Any]] = {}
        snapshots = len(rows)
        for row in reversed(rows):
            payload = self._load(row["payload_json"])
            book = payload.get("book") if isinstance(payload.get("book"), dict) else {}
            for side_key, side in (("bids", "BID"), ("asks", "ASK")):
                levels = book.get(side_key) if isinstance(book.get(side_key), list) else []
                seen_prices: set[float] = set()
                for level in levels:
                    if isinstance(level, dict):
                        price, size = level.get("price"), level.get("size", level.get("qty", level.get("quantity")))
                    elif isinstance(level, list) and len(level) >= 2:
                        price, size = level[0], level[1]
                    else:
                        continue
                    try:
                        p, q = float(price), float(size)
                    except (TypeError, ValueError):
                        continue
                    key = (side, p)
                    rec = counts.setdefault(key, {"side": side, "price": p, "appearances": 0, "samples": 0, "size_sum": 0.0, "max_size": 0.0, "last_size": None, "last_seen": None})
                    rec["samples"] += 1
                    rec["size_sum"] += q
                    rec["max_size"] = max(rec["max_size"], q)
                    rec["last_size"] = q
                    rec["last_seen"] = row["observed_at"]
                    if p not in seen_prices:
                        rec["appearances"] += 1
                        seen_prices.add(p)
        levels_out = []
        for rec in counts.values():
            persistence = rec["appearances"] / snapshots if snapshots else 0.0
            if persistence < min_persistence:
                continue
            levels_out.append({
                "side": rec["side"], "price": rec["price"],
                "persistence": round(persistence, 4),
                "appearances": rec["appearances"],
                "avg_size": round(rec["size_sum"] / rec["samples"], 4) if rec["samples"] else 0.0,
                "max_size": round(rec["max_size"], 4),
                "last_size": rec["last_size"], "last_seen": rec["last_seen"],
            })
        levels_out.sort(key=lambda x: (x["side"], x["price"]))
        return {
            "available": snapshots > 0,
            "instrument": instrument.upper(),
            "snapshots": snapshots,
            "window_limit": limit,
            "min_persistence": min_persistence,
            "levels": levels_out,
        }

    def health(self, instrument: str = "ES") -> dict[str, Any]:
        history = self.history(instrument, limit=1)
        latest = history[0] if history else None
        return {
            "ok": True,
            "version": VERSION,
            "schema_version": SCHEMA_VERSION,
            "path": self.path,
            "max_snapshots": self.max_snapshots,
            "max_age_minutes": self.max_age_minutes,
            "observations_present": bool(latest),
            "latest": latest,
        }
