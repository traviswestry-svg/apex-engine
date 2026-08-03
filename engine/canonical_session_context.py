"""APEX 50.6.2.2 durable canonical session context.

Small read-model persisted independently of process memory so weekend/replay consumers
(LTPE, readiness, replay) can recover the last known SPX reference spot and the
next-session institutional level universe after a deploy/restart.
"""
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path
from typing import Any, Mapping, Optional, List
from datetime import datetime, timezone

VERSION = "66.1.0_LIVE_ACTIVE_LEVEL_PUBLICATION"

def _default_path() -> str:
    explicit = os.getenv("APEX_CANONICAL_CONTEXT_DB")
    if explicit:
        return explicit
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/apex_canonical_context.db"
    gov = os.getenv("APEX_GOVERNANCE_DB")
    if gov:
        return str(Path(gov).with_name("apex_canonical_context.db"))
    return str(Path(__file__).resolve().parents[1] / "apex_canonical_context.db")

DB_PATH = _default_path()

def init_db(path: Optional[str] = None) -> str:
    p = path or DB_PATH
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(p, timeout=10) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS canonical_session_context(
          symbol TEXT NOT NULL,
          target_session_date TEXT NOT NULL,
          source_session_date TEXT,
          generated_at TEXT NOT NULL,
          reference_spot REAL,
          prev_close REAL,
          levels_json TEXT NOT NULL,
          source TEXT NOT NULL,
          component_version TEXT,
          PRIMARY KEY(symbol,target_session_date)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_canonical_context_latest ON canonical_session_context(symbol,generated_at DESC)")
        c.execute("""CREATE TABLE IF NOT EXISTS canonical_active_levels(
          canonical_level_id TEXT PRIMARY KEY,
          symbol TEXT NOT NULL,
          target_session_date TEXT NOT NULL,
          kind TEXT NOT NULL,
          raw_kind TEXT,
          price REAL NOT NULL,
          source TEXT,
          instrument TEXT,
          normalized INTEGER NOT NULL DEFAULT 0,
          observed_at TEXT NOT NULL,
          valid_from TEXT NOT NULL,
          valid_to TEXT,
          active INTEGER NOT NULL DEFAULT 1,
          revision INTEGER NOT NULL DEFAULT 1,
          metadata_json TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_active_levels_session ON canonical_active_levels(symbol,target_session_date,active,kind)")
    return p

def _num(v: Any) -> Optional[float]:
    try:
        if v in (None, "", "[FEED REQUIRED]"):
            return None
        x=float(v)
        return x if x > 0 else None
    except Exception:
        return None


_KIND_ALIASES = {
    "pdh":"prev_day_high", "previous_day_high":"prev_day_high",
    "pdl":"prev_day_low", "previous_day_low":"prev_day_low",
    "previous_close":"prev_close", "previous_open":"prev_open",
    "onh":"overnight_high", "onl":"overnight_low",
    "expected_move_upper":"expected_move_high", "expected_move_lower":"expected_move_low",
    "em_high":"expected_move_high", "em_low":"expected_move_low",
    "em_upper":"expected_move_high", "em_lower":"expected_move_low",
    "high_volume_node":"hvn", "low_volume_node":"lvn",
    "ib_high":"initial_balance_high", "ib_low":"initial_balance_low",
    "gammaflip":"gamma_flip", "callwall":"call_wall", "putwall":"put_wall",
}

def normalize_level_kind(value: Any) -> str:
    raw=str(value or "").strip().lower()
    return _KIND_ALIASES.get(raw, raw)

def _publish_active_levels(conn, *, symbol: str, target_session_date: str, levels: list, observed_at: str) -> dict:
    import uuid
    normalized_rows=[]
    for row in levels:
        if not isinstance(row, Mapping):
            continue
        raw=str(row.get("kind") or row.get("level_type") or row.get("type") or "").strip().lower()
        kind=normalize_level_kind(raw)
        price=_num(row.get("price") if row.get("price") is not None else row.get("value"))
        if not kind or price is None:
            continue
        normalized_rows.append((kind, raw, price, str(row.get("source") or "canonical_context"), str(row.get("instrument") or symbol), 1 if bool(row.get("normalized")) else 0, row))

    # Latest publication is authoritative for the active universe. Historical rows
    # remain queryable, but stale prices are retired rather than accumulated.
    conn.execute("UPDATE canonical_active_levels SET active=0, valid_to=? WHERE symbol=? AND target_session_date=? AND active=1",
                 (observed_at, symbol, target_session_date))
    activated=0; created=0
    for kind, raw, price, source, instrument, norm, row in normalized_rows:
        existing=conn.execute("""SELECT canonical_level_id,revision FROM canonical_active_levels
            WHERE symbol=? AND target_session_date=? AND kind=? AND ABS(price-?)<0.0001
            ORDER BY revision DESC LIMIT 1""", (symbol,target_session_date,kind,price)).fetchone()
        if existing:
            conn.execute("""UPDATE canonical_active_levels SET active=1,valid_to=NULL,observed_at=?,source=?,instrument=?,normalized=?,raw_kind=?,metadata_json=? WHERE canonical_level_id=?""",
                         (observed_at,source,instrument,norm,raw,json.dumps(row,separators=(",",":"),default=str),existing[0]))
            activated+=1
        else:
            rev=conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM canonical_active_levels WHERE symbol=? AND target_session_date=? AND kind=?",
                             (symbol,target_session_date,kind)).fetchone()[0]
            conn.execute("""INSERT INTO canonical_active_levels(canonical_level_id,symbol,target_session_date,kind,raw_kind,price,source,instrument,normalized,observed_at,valid_from,active,revision,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (str(uuid.uuid4()),symbol,target_session_date,kind,raw,price,source,instrument,norm,observed_at,observed_at,1,int(rev),json.dumps(row,separators=(",",":"),default=str)))
            created+=1
    return {"active_count":len(normalized_rows),"reactivated":activated,"created":created}

def active_levels(symbol: str="SPX", *, target_session_date: str, path: Optional[str]=None) -> List[dict]:
    p=init_db(path)
    with sqlite3.connect(p,timeout=10) as c:
        c.row_factory=sqlite3.Row
        rows=c.execute("""SELECT * FROM canonical_active_levels WHERE symbol=? AND target_session_date=? AND active=1 ORDER BY price,kind""",
                       (symbol.upper(),target_session_date)).fetchall()
        if not rows:
            # 66.0 migration path: seed the registry from the already-persisted
            # exact-session canonical context on first read after deployment.
            ctx=c.execute("SELECT levels_json,generated_at FROM canonical_session_context WHERE symbol=? AND target_session_date=? LIMIT 1",
                          (symbol.upper(),target_session_date)).fetchone()
            if ctx:
                try: levels=json.loads(ctx["levels_json"] or "[]")
                except Exception: levels=[]
                _publish_active_levels(c,symbol=symbol.upper(),target_session_date=target_session_date,levels=levels,observed_at=ctx["generated_at"] or datetime.now(timezone.utc).isoformat())
                c.commit()
                rows=c.execute("""SELECT * FROM canonical_active_levels WHERE symbol=? AND target_session_date=? AND active=1 ORDER BY price,kind""",
                               (symbol.upper(),target_session_date)).fetchall()
    return [dict(r) for r in rows]

def save_from_morning_brief(payload: Mapping[str, Any], *, symbol: str="SPX", path: Optional[str]=None) -> dict:
    p=init_db(path)
    structured=payload.get("structured") if isinstance(payload.get("structured"), Mapping) else {}
    levels=structured.get("levels") if isinstance(structured.get("levels"), list) else []
    source=str(payload.get("source_session_date") or payload.get("session_date") or "") or None
    target=str(payload.get("target_session_date") or source or "")
    if not target:
        return {"ok":False,"error":"NO_TARGET_SESSION","version":VERSION}
    generated=str(payload.get("generated_at") or "")
    reference=_num(structured.get("spot")) or _num(payload.get("spot"))
    prev_close=None
    for row in levels:
        if isinstance(row, Mapping) and str(row.get("kind") or "").lower()=="prev_close":
            prev_close=_num(row.get("price")); break
    body=json.dumps(levels, separators=(",",":"), default=str)
    with sqlite3.connect(p, timeout=10) as c:
        c.execute("""INSERT INTO canonical_session_context
          (symbol,target_session_date,source_session_date,generated_at,reference_spot,prev_close,levels_json,source,component_version)
          VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(symbol,target_session_date) DO UPDATE SET
          source_session_date=excluded.source_session_date,generated_at=excluded.generated_at,
          reference_spot=excluded.reference_spot,prev_close=excluded.prev_close,levels_json=excluded.levels_json,
          source=excluded.source,component_version=excluded.component_version""",
          (symbol.upper(),target,source,generated,reference,prev_close,body,"morning_brief",str(payload.get("version") or "")))
        registry=_publish_active_levels(c, symbol=symbol.upper(), target_session_date=target, levels=levels, observed_at=generated or datetime.now(timezone.utc).isoformat())
    return {"ok":True,"symbol":symbol.upper(),"source_session_date":source,"target_session_date":target,"reference_spot":reference,"prev_close":prev_close,"level_count":len(levels),"active_registry":registry,"version":VERSION}

def latest(symbol: str="SPX", *, target_session_date: Optional[str]=None, path: Optional[str]=None) -> Optional[dict]:
    p=init_db(path)
    with sqlite3.connect(p, timeout=10) as c:
        c.row_factory=sqlite3.Row
        if target_session_date:
            row=c.execute("SELECT * FROM canonical_session_context WHERE symbol=? AND target_session_date=? LIMIT 1",(symbol.upper(),target_session_date)).fetchone()
        else:
            row=c.execute("SELECT * FROM canonical_session_context WHERE symbol=? ORDER BY generated_at DESC LIMIT 1",(symbol.upper(),)).fetchone()
    if not row: return None
    out=dict(row)
    try: out["levels"]=json.loads(out.pop("levels_json") or "[]")
    except Exception: out["levels"]=[]
    out["version"]=VERSION
    return out

# ---------------------------------------------------------------------------
# APEX 66.1 — selective live active-level publication
# ---------------------------------------------------------------------------
LIVE_MUTABLE_LEVEL_KINDS = {
    "developing_poc", "vah", "val", "hvn", "lvn",
    "swing_high", "swing_low", "fair_value_gap",
    "buyside_liquidity", "sellside_liquidity", "unfilled_gap",
    "large_option_strike", "dealer_hedge_zone",
    "gamma_flip", "zero_gamma", "call_wall", "put_wall",
    "high_gamma_strike", "low_gamma_strike", "volatility_trigger",
    "or5_high", "or5_low", "or15_high", "or15_low",
    "initial_balance_high", "initial_balance_low", "ib_extension",
}


def _registry_rows_as_level_payload(conn, *, symbol: str, target_session_date: str) -> list:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM canonical_active_levels
           WHERE symbol=? AND target_session_date=? AND active=1
           ORDER BY price,kind,revision""",
        (symbol, target_session_date),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        try:
            meta = json.loads(d.get("metadata_json") or "{}")
        except Exception:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta.update({
            "canonical_level_id": d.get("canonical_level_id"),
            "kind": d.get("kind"),
            "raw_kind": d.get("raw_kind"),
            "price": d.get("price"),
            "source": d.get("source"),
            "instrument": d.get("instrument"),
            "normalized": bool(d.get("normalized")),
            "observed_at": d.get("observed_at"),
            "revision": d.get("revision"),
            "active": True,
        })
        result.append(meta)
    return result


def publish_live_levels(
    levels: list,
    *,
    symbol: str = "SPX",
    target_session_date: str,
    observed_at: Optional[str] = None,
    reference_spot: Optional[float] = None,
    mutable_kinds: Optional[set] = None,
    authoritative_kinds: Optional[set] = None,
    source: str = "live_active_level_publisher",
    component_version: str = "66.1.1_ACTIVE_LEVEL_RECONCILIATION",
    path: Optional[str] = None,
) -> dict:
    """Reconcile mutable intraday levels by set-diff, preserving stable lifecycle state.

    For each authoritative mutable kind, current active rows are compared with the
    newly published set. Matching rows remain active and are refreshed in place;
    only missing rows are retired, only previously inactive matching rows are
    reactivated, and genuinely new prices create a new revision. Static kinds are
    untouched. This prevents artificial retire/reactivate churn on every cycle.
    """
    p = init_db(path)
    symbol = symbol.upper()
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    allowed = {normalize_level_kind(k) for k in (mutable_kinds or LIVE_MUTABLE_LEVEL_KINDS)}

    # Normalize and de-duplicate a publication by canonical (kind, price).
    by_key = {}
    for row in levels or []:
        if not isinstance(row, Mapping):
            continue
        raw = str(row.get("kind") or row.get("level_type") or row.get("type") or "").strip().lower()
        kind = normalize_level_kind(raw)
        if kind not in allowed:
            continue
        price = _num(row.get("price") if row.get("price") is not None else row.get("value"))
        if not kind or price is None:
            continue
        key = (kind, round(float(price), 4))
        by_key[key] = {
            "kind": kind,
            "raw_kind": raw,
            "price": float(price),
            "source": str(row.get("source") or source),
            "instrument": str(row.get("instrument") or symbol),
            "normalized": 1 if bool(row.get("normalized")) else 0,
            "metadata": dict(row),
        }
    normalized_rows = list(by_key.values())

    published_kinds = {r["kind"] for r in normalized_rows}
    scope_kinds = {normalize_level_kind(k) for k in (authoritative_kinds or published_kinds)}
    scope_kinds &= allowed
    if not scope_kinds:
        return {
            "ok": False,
            "state": "NO_MUTABLE_LEVELS_AVAILABLE",
            "symbol": symbol,
            "target_session_date": target_session_date,
            "observed_at": observed_at,
            "published_kinds": [],
            "active_count": len(active_levels(symbol, target_session_date=target_session_date, path=p)),
            "version": component_version,
        }

    created = 0
    reactivated = 0
    retired = 0
    refreshed = 0
    unchanged = 0
    with sqlite3.connect(p, timeout=10) as c:
        c.row_factory = sqlite3.Row
        new_by_kind = {}
        for row in normalized_rows:
            new_by_kind.setdefault(row["kind"], {})[round(float(row["price"]), 4)] = row

        # True set-diff: retire only active rows that disappeared from an
        # authoritative domain. Rows still present never transition lifecycle.
        for kind in sorted(scope_kinds):
            active_rows = c.execute(
                """SELECT canonical_level_id,price FROM canonical_active_levels
                   WHERE symbol=? AND target_session_date=? AND kind=? AND active=1""",
                (symbol, target_session_date, kind),
            ).fetchall()
            new_prices = set(new_by_kind.get(kind, {}))
            for existing in active_rows:
                if round(float(existing["price"]), 4) not in new_prices:
                    cur = c.execute(
                        "UPDATE canonical_active_levels SET active=0,valid_to=? WHERE canonical_level_id=? AND active=1",
                        (observed_at, existing["canonical_level_id"]),
                    )
                    retired += int(cur.rowcount or 0)

        for row in normalized_rows:
            key_price = round(float(row["price"]), 4)
            payload = json.dumps(row["metadata"], separators=(",", ":"), default=str)
            active_existing = c.execute(
                """SELECT canonical_level_id,revision,source,instrument,normalized,raw_kind,metadata_json
                   FROM canonical_active_levels
                   WHERE symbol=? AND target_session_date=? AND kind=? AND active=1 AND ABS(price-?)<0.0001
                   ORDER BY revision DESC LIMIT 1""",
                (symbol, target_session_date, row["kind"], row["price"]),
            ).fetchone()
            if active_existing:
                # Stay active: refresh observation/provider metadata in place.
                c.execute(
                    """UPDATE canonical_active_levels
                       SET observed_at=?,source=?,instrument=?,normalized=?,raw_kind=?,metadata_json=?
                       WHERE canonical_level_id=?""",
                    (observed_at, row["source"], row["instrument"], row["normalized"], row["raw_kind"], payload, active_existing["canonical_level_id"]),
                )
                refreshed += 1
                if (str(active_existing["source"] or "") == row["source"] and
                    str(active_existing["instrument"] or "") == row["instrument"] and
                    int(active_existing["normalized"] or 0) == row["normalized"] and
                    str(active_existing["raw_kind"] or "") == row["raw_kind"] and
                    str(active_existing["metadata_json"] or "") == payload):
                    unchanged += 1
                continue

            inactive_existing = c.execute(
                """SELECT canonical_level_id,revision FROM canonical_active_levels
                   WHERE symbol=? AND target_session_date=? AND kind=? AND active=0 AND ABS(price-?)<0.0001
                   ORDER BY revision DESC LIMIT 1""",
                (symbol, target_session_date, row["kind"], row["price"]),
            ).fetchone()
            if inactive_existing:
                c.execute(
                    """UPDATE canonical_active_levels
                       SET active=1,valid_to=NULL,observed_at=?,source=?,instrument=?,normalized=?,raw_kind=?,metadata_json=?
                       WHERE canonical_level_id=?""",
                    (observed_at, row["source"], row["instrument"], row["normalized"], row["raw_kind"], payload, inactive_existing["canonical_level_id"]),
                )
                reactivated += 1
            else:
                import uuid
                rev = c.execute(
                    "SELECT COALESCE(MAX(revision),0)+1 FROM canonical_active_levels WHERE symbol=? AND target_session_date=? AND kind=?",
                    (symbol, target_session_date, row["kind"]),
                ).fetchone()[0]
                c.execute(
                    """INSERT INTO canonical_active_levels
                       (canonical_level_id,symbol,target_session_date,kind,raw_kind,price,source,instrument,normalized,observed_at,valid_from,active,revision,metadata_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), symbol, target_session_date, row["kind"], row["raw_kind"], row["price"], row["source"], row["instrument"], row["normalized"], observed_at, observed_at, 1, int(rev), payload),
                )
                created += 1

        active_payload = _registry_rows_as_level_payload(c, symbol=symbol, target_session_date=target_session_date)
        prior = c.execute(
            "SELECT source_session_date,prev_close,reference_spot FROM canonical_session_context WHERE symbol=? AND target_session_date=?",
            (symbol, target_session_date),
        ).fetchone()
        source_session_date = prior[0] if prior else target_session_date
        prev_close = prior[1] if prior else None
        prior_spot = prior[2] if prior else None
        spot = _num(reference_spot) or _num(prior_spot)
        c.execute(
            """INSERT INTO canonical_session_context
               (symbol,target_session_date,source_session_date,generated_at,reference_spot,prev_close,levels_json,source,component_version)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(symbol,target_session_date) DO UPDATE SET
               generated_at=excluded.generated_at,reference_spot=excluded.reference_spot,
               levels_json=excluded.levels_json,source=excluded.source,component_version=excluded.component_version""",
            (symbol, target_session_date, source_session_date, observed_at, spot, prev_close,
             json.dumps(active_payload, separators=(",", ":"), default=str), source, component_version),
        )
        c.commit()

    return {
        "ok": True,
        "state": "LIVE_LEVELS_RECONCILED",
        "symbol": symbol,
        "target_session_date": target_session_date,
        "observed_at": observed_at,
        "published_kinds": sorted(published_kinds),
        "authoritative_kinds": sorted(scope_kinds),
        "published_rows": len(normalized_rows),
        "created": created,
        "reactivated": reactivated,
        "retired": retired,
        "refreshed": refreshed,
        "unchanged": unchanged,
        "active_count": len(active_levels(symbol, target_session_date=target_session_date, path=p)),
        "source": source,
        "version": component_version,
    }
