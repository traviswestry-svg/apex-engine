"""Flask routes for APEX 18.0.8 Premium Discipline Command Center."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, Optional

from flask import jsonify, render_template, request

from .confluence import build_confluence
from .premium_discipline import RefusalLedger, evaluate_premium_eligibility
from .premium_strategy import build_premium_strategy
from .refusal_replay import replay_due_refusals
from .adaptive_refusal_calibration import CalibrationStore
from .premium_command_center import build_command_center
from .institutional_premium_intelligence import rank_premium_strategies

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
    calibration = CalibrationStore(db_path)

    def snapshot(ticker: str) -> Dict[str, Any]:
        lr = (last_result_provider() or {}) if last_result_provider else {}
        now = dt.datetime.now(ET)
        candidate = build_premium_strategy(
            lr, confluence=build_confluence(lr), chain_fetcher=chain_fetcher,
            now_et=now, symbol=ticker, expiration=now.date().isoformat())
        policy = calibration.active_policy()
        gate = evaluate_premium_eligibility(lr, candidate, threshold=policy.get("threshold"),
                                            weights=policy.get("weights"))
        gate["policy"] = policy
        rec = ledger.record(session_date=now.date().isoformat(), ticker=ticker,
                            candidate=candidate, decision=gate)
        return {"candidate": candidate, "eligibility": gate, "ledger": rec}

    @app.route("/apex_os/premium_discipline")
    def premium_discipline_command_center_page():
        return render_template("premium_discipline_command_center.html")

    @app.route("/api/premium_discipline/command-center")
    def premium_discipline_command_center():
        ticker = (request.args.get("ticker") or "SPX").upper()
        try:
            limit = max(1, min(int(request.args.get("limit") or 100), 500))
        except ValueError:
            limit = 100
        current = snapshot(ticker)
        runs = calibration.recent(limit=20)
        policy = calibration.active_policy()
        lr = (last_result_provider() or {}) if last_result_provider else {}
        now = dt.datetime.now(ET)
        intelligence = rank_premium_strategies(
            lr, chain_fetcher=chain_fetcher, now_et=now, symbol=ticker,
            expiration=now.date().isoformat(), threshold=policy.get("threshold"),
            weights=policy.get("weights"))
        payload = build_command_center(
            snapshot=current, decisions=ledger.recent(limit=limit),
            scorecard=ledger.scorecard(), replay=ledger.replay_scorecard(),
            active_policy=policy, calibration_runs=runs,
            premium_intelligence=intelligence,
        )
        return jsonify({"ok": True, "ticker": ticker, "command_center": payload})

    @app.route("/api/premium_discipline/intelligence")
    def premium_discipline_intelligence():
        ticker = (request.args.get("ticker") or "SPX").upper()
        lr = (last_result_provider() or {}) if last_result_provider else {}
        now = dt.datetime.now(ET)
        policy = calibration.active_policy()
        result = rank_premium_strategies(
            lr, chain_fetcher=chain_fetcher, now_et=now, symbol=ticker,
            expiration=now.date().isoformat(), threshold=policy.get("threshold"),
            weights=policy.get("weights"))
        return jsonify({"ok": True, "ticker": ticker, "premium_intelligence": result})

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

    @app.route("/api/premium_discipline/calibration")
    def premium_discipline_calibration():
        try:
            limit = int(request.args.get("limit") or 20)
        except ValueError:
            limit = 20
        return jsonify({"ok": True, "active_policy": calibration.active_policy(),
                        "runs": calibration.recent(limit=limit)})

    @app.route("/api/premium_discipline/calibration/run", methods=["POST"])
    def premium_discipline_calibration_run():
        payload = request.get_json(silent=True) or {}
        try:
            min_sample = int(payload.get("min_sample", request.args.get("min_sample") or 20))
            lookback = int(payload.get("lookback", request.args.get("lookback") or 500))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "min_sample and lookback must be integers."}), 400
        result = calibration.run(min_sample=max(5, min_sample), lookback=max(1, lookback))
        return jsonify({"ok": True, "calibration": result})

    @app.route("/api/premium_discipline/calibration/promote", methods=["POST"])
    def premium_discipline_calibration_promote():
        payload = request.get_json(silent=True) or {}
        try:
            run_id = int(payload.get("run_id"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "run_id is required."}), 400
        promoted_by = str(payload.get("promoted_by") or "operator")[:120]
        try:
            result = calibration.promote(run_id, promoted_by=promoted_by)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({"ok": True, "promotion": result})

