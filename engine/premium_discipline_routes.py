"""Flask routes for APEX 18.0.6 Premium Discipline and Refusal Replay."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, Optional

from flask import jsonify, request

from .confluence import build_confluence
from .premium_discipline import RefusalLedger, evaluate_premium_eligibility
from .premium_strategy import build_premium_strategy
from .refusal_replay import replay_due_refusals

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = dt.timezone.utc


def register_premium_discipline_routes(app, *, last_result_provider: Callable[[], Dict[str, Any]],
                                       chain_fetcher: Optional[Callable[..., Any]] = None,
                                       get_intraday_bars: Optional[Callable[..., Any]] = None,
                                       db_path: Optional[str] = None) -> None:
    ledger = RefusalLedger(db_path)

    def snapshot(ticker: str) -> Dict[str, Any]:
        lr = (last_result_provider() or {}) if last_result_provider else {}
        now = dt.datetime.now(ET)
        candidate = build_premium_strategy(
            lr, confluence=build_confluence(lr), chain_fetcher=chain_fetcher,
            now_et=now, symbol=ticker, expiration=now.date().isoformat())
        gate = evaluate_premium_eligibility(lr, candidate)
        rec = ledger.record(session_date=now.date().isoformat(), ticker=ticker,
                            candidate=candidate, decision=gate)
        return {"candidate": candidate, "eligibility": gate, "ledger": rec}

    @app.route("/api/premium_discipline")
    def premium_discipline():
        try:
            ticker = (request.args.get("ticker") or "SPX").upper()
            return jsonify({"ok": True, "ticker": ticker, "premium_discipline": snapshot(ticker)})
        except Exception as exc:
            return jsonify({"ok": True, "premium_discipline": {
                "candidate": {"strategy": "NO_TRADE", "tradeable": False},
                "eligibility": {"decision": "REFUSE", "eligible": False, "score": 0,
                                "blockers": [f"Premium discipline recovered safely: {exc}"],
                                "headline": "STAND DOWN — PREMIUM SELLING REFUSED"},
                "ledger": {"recorded": False},
            }})

    @app.route("/api/premium_discipline/decisions")
    def premium_discipline_decisions():
        decision = request.args.get("decision")
        try:
            limit = int(request.args.get("limit") or 50)
        except ValueError:
            limit = 50
        return jsonify({"ok": True, "decisions": ledger.recent(limit=limit, decision=decision)})

    @app.route("/api/premium_discipline/scorecard")
    def premium_discipline_scorecard():
        return jsonify({"ok": True, "scorecard": ledger.scorecard(),
                        "replay": ledger.replay_scorecard()})

    @app.route("/api/premium_discipline/replay")
    def premium_discipline_replay():
        return jsonify({"ok": True, "replay": ledger.replay_scorecard()})

    @app.route("/api/premium_discipline/replay/run", methods=["POST"])
    def premium_discipline_replay_run():
        if get_intraday_bars is None:
            return jsonify({"ok": False, "error": "Intraday bar provider is unavailable."}), 503
        try:
            limit = int(request.args.get("limit") or 300)
        except ValueError:
            limit = 300
        result = replay_due_refusals(ledger, get_intraday_bars, limit=limit)
        return jsonify({"ok": True, "run": result, "replay": ledger.replay_scorecard()})
