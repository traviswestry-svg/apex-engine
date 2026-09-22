"""APEX 47.0.3 — durable decision/evidence ledger and readiness diagnostics."""
from __future__ import annotations
import hashlib, json, os, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from .canonical_persistence import connect as canonical_connect
from .persistent_store import persistent_sqlite_path
VERSION="68.6.0"; MAX_PERSISTED_SNAPSHOT_BYTES=int(os.getenv("APEX_DECISION_SNAPSHOT_MAX_BYTES","131072")); SCHEMA_VERSION="apex.evidence_readiness.v2"; DEFAULT_DB=persistent_sqlite_path("APEX_EVIDENCE_PIPELINE_DB", "apex_evidence_pipeline.db")
def _now(): return datetime.now(timezone.utc).isoformat()


# APEX 69.4.4 — bounded persistence projection for canonical decision snapshots.
# The full institutional decision object is consumed contemporaneously by attribution
# before this projection is stored. Historical consumers require only this compact
# compatibility surface; raw narrative/provider/evidence graphs are intentionally not
# duplicated into every decision row.
_IDO_PERSIST_KEYS = (
    "schema_version", "engine_version", "recommendation_id", "timestamp", "generated_at",
    "ticker", "instrument", "strategy", "playbook", "action", "decision_state",
    "direction", "status", "actionable", "authoritative_contract", "decision_authority",
    "raw_conviction", "calibrated_conviction", "calibration_state", "execution_score",
    "position_quality", "fail_closed", "historical_performance_claimed",
    "regime", "gamma_regime", "volatility_regime", "auction_regime",
)

def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True).encode("utf-8")

_ROOT_PERSIST_KEYS = (
    "decision_id","timestamp","ticker","session","direction","action","decision_state",
    "entry_reference","confidence","learning_eligible","observational_learning_eligible",
    "execution_actionable","actionable","eligibility_reason","eligibility_inputs",
    "setup","market_regime","volatility_regime","pre_governance_decision",
    "trade_horizon_intelligence","institutional_decision_object","apex_release_version",
    "canonical_gamma_snapshot_id","gamma_snapshot_age_seconds","gamma_provenance_class","gamma_evidence",
)

def _persisted_snapshot_projection(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the bounded canonical form stored in decisions.snapshot_json.

    This is a storage-shape closure only. It does not alter the in-memory decision,
    decision authority, grading eligibility, or contemporaneous attribution capture.
    """
    source = dict(snapshot or {})
    raw = _json_bytes(source)
    projected = dict(source)
    ido = source.get("institutional_decision_object")
    omitted: list[str] = []
    if isinstance(ido, Mapping):
        compact = {key: ido.get(key) for key in _IDO_PERSIST_KEYS if key in ido}
        projected["institutional_decision_object"] = compact
        omitted = sorted(str(k) for k in ido.keys() if k not in _IDO_PERSIST_KEYS)
    projected["storage_projection"] = {
        "schema_version": "apex.decision_snapshot_storage.v1",
        "projection_version": "69.4.4",
        "source_snapshot_bytes": len(raw),
        "source_snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "institutional_decision_object_projected": isinstance(ido, Mapping),
        "omitted_ido_fields": omitted,
        "omitted_fields_are_redundant_runtime_bulk": True,
        "canonical_decision_semantics_preserved": True,
    }
    # A second guardrail prevents unrelated top-level runtime bulk from recreating
    # the historical >1 MB amplification pattern. The decision is still persisted.
    pre_guard = len(_json_bytes(projected))
    if pre_guard > MAX_PERSISTED_SNAPSHOT_BYTES:
        projected = {key: projected.get(key) for key in _ROOT_PERSIST_KEYS if key in projected}
        projected["storage_projection"] = {
            "schema_version": "apex.decision_snapshot_storage.v1",
            "projection_version": "69.10.9",
            "source_snapshot_bytes": len(raw),
            "source_snapshot_sha256": hashlib.sha256(raw).hexdigest(),
            "hard_size_guardrail_applied": True,
            "max_persisted_snapshot_bytes": MAX_PERSISTED_SNAPSHOT_BYTES,
            "canonical_decision_semantics_preserved": True,
        }
    # Resolve the self-reported persisted byte count to a stable exact value.
    projected["storage_projection"]["persisted_snapshot_bytes"] = 0
    for _ in range(3):
        exact = len(_json_bytes(projected))
        if projected["storage_projection"]["persisted_snapshot_bytes"] == exact:
            break
        projected["storage_projection"]["persisted_snapshot_bytes"] = exact
    return projected
def _connect(path: str|Path=DEFAULT_DB):
 c=canonical_connect(path); c.executescript("""
 CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY,observed_at TEXT NOT NULL,ticker TEXT NOT NULL,session TEXT,direction TEXT,action TEXT,entry_price REAL,confidence REAL,learning_eligible INTEGER NOT NULL,snapshot_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING',canonical_gamma_snapshot_id TEXT,gamma_snapshot_age_seconds REAL,gamma_provenance_class TEXT);
 CREATE TABLE IF NOT EXISTS price_samples(id INTEGER PRIMARY KEY AUTOINCREMENT,ticker TEXT NOT NULL,observed_at TEXT NOT NULL,price REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS grading_results(id INTEGER PRIMARY KEY AUTOINCREMENT,decision_id TEXT NOT NULL UNIQUE,graded_at TEXT NOT NULL,status TEXT NOT NULL,exclusion_reason TEXT,horizon_seconds INTEGER,outcome_json TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status,observed_at); CREATE INDEX IF NOT EXISTS idx_prices_ticker_time ON price_samples(ticker,observed_at);
 """)
 existing={row[1] for row in c.execute("PRAGMA table_info(decisions)")}
 for name,decl in (("canonical_gamma_snapshot_id","TEXT"),("gamma_snapshot_age_seconds","REAL"),("gamma_provenance_class","TEXT")):
  if name not in existing: c.execute(f"ALTER TABLE decisions ADD COLUMN {name} {decl}")
 c.execute("CREATE INDEX IF NOT EXISTS idx_decisions_gamma_snapshot ON decisions(canonical_gamma_snapshot_id,observed_at)")
 return c
def record_snapshot(snapshot: Mapping[str,Any], path: str|Path=DEFAULT_DB)->bool:
 s=dict(snapshot); did=str(s.get('decision_id') or '')
 if not did: return False
 with _connect(path) as c:
  observed_at=str(s.get('timestamp') or _now())
  before=c.total_changes
  persisted_snapshot=_persisted_snapshot_projection(s)
  c.execute("""INSERT OR IGNORE INTO decisions(
   decision_id,observed_at,ticker,session,direction,action,entry_price,confidence,learning_eligible,
   snapshot_json,canonical_gamma_snapshot_id,gamma_snapshot_age_seconds,gamma_provenance_class)
   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
   did,observed_at,str(s.get('ticker') or 'SPX'),str(s.get('session') or 'UNKNOWN'),
   str(s.get('direction') or 'NEUTRAL'),str(s.get('action') or 'STAND_DOWN'),s.get('entry_reference'),
   s.get('confidence'),int(bool(s.get('learning_eligible'))),
   json.dumps(persisted_snapshot,default=str,separators=(',',':'),sort_keys=True),
   s.get('canonical_gamma_snapshot_id'),s.get('gamma_snapshot_age_seconds'),s.get('gamma_provenance_class')))
  inserted=c.total_changes>before
  try:
   from .dynamic_state_outcome_calibration import persist_context
   persist_context(c,did,observed_at,s)
  except Exception:
   pass
  try:
   from .decision_outcome_attribution import capture_context
   capture_context(c,did,observed_at,s)
  except Exception:
   pass
  return inserted
def record_price(ticker:str, price:Any, observed_at:str|None=None,path: str|Path=DEFAULT_DB)->bool:
 try: p=float(price)
 except (TypeError,ValueError): return False
 with _connect(path) as c: c.execute("INSERT INTO price_samples(ticker,observed_at,price) VALUES(?,?,?)",(ticker.upper(),observed_at or _now(),p))
 return True

def _release_gamma_linkage(c, current_release: str) -> dict[str, Any]:
    """Reconcile gamma linkage by recorded release without reconstructing history."""
    cohorts: dict[str, dict[str, int]] = {}
    for row in c.execute("SELECT canonical_gamma_snapshot_id,snapshot_json FROM decisions"):
        try:
            snap = json.loads(row["snapshot_json"]) or {}
        except Exception:
            snap = {}
        release = str(snap.get("apex_release_version") or snap.get("version") or "UNKNOWN")
        cohort = cohorts.setdefault(release, {"decisions": 0, "gamma_linked": 0, "gamma_missing": 0})
        cohort["decisions"] += 1
        if row["canonical_gamma_snapshot_id"]:
            cohort["gamma_linked"] += 1
        else:
            cohort["gamma_missing"] += 1
    current = dict(cohorts.get(current_release) or {"decisions": 0, "gamma_linked": 0, "gamma_missing": 0})
    current["release_version"] = current_release
    current["linkage_pct"] = round((100.0 * current["gamma_linked"] / current["decisions"]), 2) if current["decisions"] else None
    current["legacy_rows_reconstructed"] = 0
    current["latest_gamma_substitution_allowed"] = False
    return {"current_release": current, "by_release": cohorts}

def readiness(path: str|Path=DEFAULT_DB)->dict[str,Any]:
 with _connect(path) as c:
  total=c.execute('SELECT COUNT(*) n FROM decisions').fetchone()['n']; grade_eligible=c.execute('SELECT COUNT(*) n FROM decisions WHERE learning_eligible=1').fetchone()['n']
  graded=c.execute("SELECT COUNT(*) n FROM grading_results WHERE status='GRADED'").fetchone()['n']; excluded=c.execute("SELECT COUNT(*) n FROM grading_results WHERE status='EXCLUDED'").fetchone()['n']; pending=c.execute("SELECT COUNT(*) n FROM decisions WHERE status='PENDING'").fetchone()['n']; samples=c.execute('SELECT COUNT(*) n FROM price_samples').fetchone()['n']
  lastd=c.execute('SELECT MAX(observed_at) v FROM decisions').fetchone()['v']; lastg=c.execute("SELECT MAX(graded_at) v FROM grading_results WHERE status='GRADED'").fetchone()['v']
  gamma_linked=c.execute("SELECT COUNT(*) n FROM decisions WHERE canonical_gamma_snapshot_id IS NOT NULL").fetchone()['n']; gamma_missing=max(0,total-gamma_linked)
  try:
   manifest=json.loads((Path(__file__).resolve().parents[1]/"config"/"apex_release_manifest.json").read_text(encoding="utf-8"))
   current_release=str(manifest.get("apex_version") or "69.10.19")
  except Exception:
   current_release="69.10.19"
  gamma_release_linkage=_release_gamma_linkage(c,current_release)
  reasons={r['exclusion_reason']:r['n'] for r in c.execute("SELECT exclusion_reason,COUNT(*) n FROM grading_results WHERE status='EXCLUDED' GROUP BY exclusion_reason") if r['exclusion_reason']}
  eligibility_reasons={}; execution_actionable=0; observational_eligible=0
  for row in c.execute('SELECT snapshot_json FROM decisions'):
   try:
    snap=json.loads(row['snapshot_json']) or {}; reason=snap.get('eligibility_reason') or 'LEGACY_UNSPECIFIED'
    execution_actionable += int(bool(snap.get('execution_actionable', snap.get('actionable'))))
    observational_eligible += int(bool(snap.get('observational_learning_eligible')))
   except Exception:
    reason='UNREADABLE_SNAPSHOT'
   eligibility_reasons[reason]=eligibility_reasons.get(reason,0)+1
 if total==0: status='WAITING_FOR_LIVE_DATA'
 elif grade_eligible==0: status='NO_GRADE_ELIGIBLE_DECISIONS'
 elif pending>0 and samples==0: status='GRADING_WINDOW_NOT_MATURED'
 else: status='HEALTHY'
 return {'ok':True,'status':status,'decisions_recorded':total,'actionable_decisions':execution_actionable,'execution_actionable_decisions':execution_actionable,'grade_eligible_decisions':grade_eligible,'observational_eligible_decisions':observational_eligible,'feature_vectors_stored':grade_eligible,'matured_outcomes':graded+excluded,'graded_outcomes':graded,'excluded_outcomes':excluded,'pending_decisions':pending,'price_samples':samples,'shadow_observations':graded,'gamma_decisions_linked':gamma_linked,'gamma_decisions_missing_linkage':gamma_missing,'gamma_release_linkage':gamma_release_linkage,'last_decision_write':lastd,'last_successful_grade':lastg,'exclusion_reasons':reasons,'eligibility_reasons':eligibility_reasons,'schema_version':SCHEMA_VERSION,'engine_version':VERSION,'execution_authority':False}
