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
from .institutional_expectancy_intelligence import ExpectancyStore, build_expectancy_intelligence
from .dynamic_position_sizing import build_position_sizing
from .multi_strategy_portfolio_optimizer import build_portfolio_optimizer
from .portfolio_outcome_attribution import PortfolioOutcomeStore, replay_due_portfolios
from .adaptive_portfolio_calibration import PortfolioCalibrationStore
from .execution_reality_slippage import ExecutionRealityStore, build_execution_reality, evaluate_candidate_execution
from .premium_portfolio_risk_governor import RiskGovernorStore, evaluate_portfolio_risk
from .premium_execution_orchestrator import PremiumExecutionOrchestrator
from .institutional_learning_engine import LearningStore, build_learning_intelligence
from .decision_narrative import build_decision_narrative
from .trade_lifecycle_intelligence import LifecycleStore, evaluate_trade_lifecycle

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
    expectancy = ExpectancyStore(db_path)
    portfolio_outcomes = PortfolioOutcomeStore(db_path)
    portfolio_calibration = PortfolioCalibrationStore(db_path)
    execution_reality_store = ExecutionRealityStore(db_path)
    risk_governor_store = RiskGovernorStore(db_path)
    execution_orchestrator = PremiumExecutionOrchestrator(db_path)
    learning_store = LearningStore(db_path)
    lifecycle_store = LifecycleStore(db_path)

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
        expectancy_intelligence = build_expectancy_intelligence(
            lr, store=expectancy, ticker=ticker, chain_fetcher=chain_fetcher,
            now_et=now, expiration=now.date().isoformat(), threshold=policy.get("threshold"),
            weights=policy.get("weights"))
        payload = build_command_center(
            snapshot=current, decisions=ledger.recent(limit=limit),
            scorecard=ledger.scorecard(), replay=ledger.replay_scorecard(),
            active_policy=policy, calibration_runs=runs,
            premium_intelligence=intelligence,
        )
        payload["expectancy_intelligence"] = expectancy_intelligence
        payload["position_sizing"] = build_position_sizing(expectancy_intelligence, daily_realized_pnl=float(request.args.get("daily_pnl") or 0), open_risk=float(request.args.get("open_risk") or 0))
        payload["portfolio_optimizer"] = build_portfolio_optimizer(expectancy_intelligence, daily_realized_pnl=float(request.args.get("daily_pnl") or 0), open_risk=float(request.args.get("open_risk") or 0), account_size=float(request.args["account_size"]) if request.args.get("account_size") else None, allocation_policy=portfolio_calibration.active_policy())
        payload["portfolio_outcome_record"] = portfolio_outcomes.record(ticker, payload["portfolio_optimizer"], observed_at=now)
        payload["portfolio_outcome_attribution"] = portfolio_outcomes.scorecard()
        payload["portfolio_calibration"] = {"active_policy": portfolio_calibration.active_policy(), "runs": portfolio_calibration.recent(limit=10)}
        payload["execution_reality"] = build_execution_reality(expectancy_intelligence)
        recommendation = payload["execution_reality"].get("recommendation")
        payload["execution_reality_record"] = execution_reality_store.record_shadow(ticker, recommendation, observed_at=now) if recommendation else None
        payload["execution_reality_scorecard"] = execution_reality_store.scorecard()
        payload["portfolio_risk_governor"] = evaluate_portfolio_risk(
            payload["portfolio_optimizer"], payload["execution_reality"],
            daily_realized_pnl=float(request.args.get("daily_pnl") or 0),
            open_risk=float(request.args.get("open_risk") or 0),
            trades_today=int(request.args.get("trades_today") or 0),
            losses_today=int(request.args.get("losses_today") or 0),
            account_size=float(request.args["account_size"]) if request.args.get("account_size") else None)
        payload["portfolio_risk_governor_record"] = risk_governor_store.record(ticker, payload["portfolio_risk_governor"], observed_at=now)
        payload["execution_orchestrator"] = {"recent_intents": execution_orchestrator.recent(10), "execution_enabled": False, "confirmation_required": True}
        current_context = {
            "ticker": ticker,
            "premium_regime": (intelligence or {}).get("regime"),
            "direction": (intelligence or {}).get("direction"),
            "auction_state": lr.get("auction_state") or lr.get("auction", {}).get("state") if isinstance(lr, dict) else None,
            "gamma_regime": lr.get("gamma_regime") if isinstance(lr, dict) else None,
            "vix_regime": lr.get("vix_regime") if isinstance(lr, dict) else None,
        }
        payload["institutional_learning"] = build_learning_intelligence(learning_store, current_context)
        payload["decision_narrative"] = build_decision_narrative(
            eligibility=current.get("eligibility") or {}, intelligence=intelligence or {},
            portfolio=payload["portfolio_optimizer"], execution=payload["execution_reality"],
            risk=payload["portfolio_risk_governor"], learning=payload["institutional_learning"])
        payload["trade_lifecycle_intelligence"] = {"recent_events": lifecycle_store.recent(20), "advisory_only": True}
        return jsonify({"ok": True, "ticker": ticker, "command_center": payload})

    @app.route("/api/premium_discipline/expectancy")
    def premium_discipline_expectancy():
        ticker = (request.args.get("ticker") or "SPX").upper()
        lr = (last_result_provider() or {}) if last_result_provider else {}
        now = dt.datetime.now(ET)
        policy = calibration.active_policy()
        result = build_expectancy_intelligence(
            lr, store=expectancy, ticker=ticker, chain_fetcher=chain_fetcher,
            now_et=now, expiration=now.date().isoformat(),
            threshold=policy.get("threshold"), weights=policy.get("weights"))
        return jsonify({"ok": True, "ticker": ticker, "expectancy_intelligence": result})

    @app.route("/api/premium_discipline/position-sizing")
    def premium_discipline_position_sizing():
        ticker = (request.args.get("ticker") or "SPX").upper()
        lr = (last_result_provider() or {}) if last_result_provider else {}
        now = dt.datetime.now(ET)
        policy = calibration.active_policy()
        exp = build_expectancy_intelligence(lr, store=expectancy, ticker=ticker, chain_fetcher=chain_fetcher, now_et=now, expiration=now.date().isoformat(), threshold=policy.get("threshold"), weights=policy.get("weights"))
        try:
            result = build_position_sizing(exp, daily_realized_pnl=float(request.args.get("daily_pnl") or 0), open_risk=float(request.args.get("open_risk") or 0), account_size=float(request.args["account_size"]) if request.args.get("account_size") else None)
        except ValueError:
            return jsonify({"ok": False, "error": "daily_pnl, open_risk, and account_size must be numeric."}), 400
        return jsonify({"ok": True, "ticker": ticker, "position_sizing": result})

    @app.route("/api/premium_discipline/portfolio")
    @app.route("/api/premium_discipline/portfolio/allocation")
    @app.route("/api/premium_discipline/portfolio/risk")
    def premium_discipline_portfolio():
        ticker = (request.args.get("ticker") or "SPX").upper()
        lr = (last_result_provider() or {}) if last_result_provider else {}
        now = dt.datetime.now(ET)
        policy = calibration.active_policy()
        exp = build_expectancy_intelligence(lr, store=expectancy, ticker=ticker, chain_fetcher=chain_fetcher, now_et=now, expiration=now.date().isoformat(), threshold=policy.get("threshold"), weights=policy.get("weights"))
        try:
            result = build_portfolio_optimizer(
                exp, daily_realized_pnl=float(request.args.get("daily_pnl") or 0),
                open_risk=float(request.args.get("open_risk") or 0),
                account_size=float(request.args["account_size"]) if request.args.get("account_size") else None,
                max_portfolio_risk=float(request.args["max_portfolio_risk"]) if request.args.get("max_portfolio_risk") else None,
                allocation_policy=portfolio_calibration.active_policy(),
            )
        except ValueError:
            return jsonify({"ok": False, "error": "Risk and account query inputs must be numeric."}), 400
        return jsonify({"ok": True, "ticker": ticker, "portfolio_optimizer": result})


    @app.route("/api/premium_discipline/portfolio/outcomes")
    def premium_discipline_portfolio_outcomes():
        try: limit = max(1, min(int(request.args.get("limit") or 100), 500))
        except ValueError: limit = 100
        return jsonify({"ok": True, "outcomes": portfolio_outcomes.recent(limit), "scorecard": portfolio_outcomes.scorecard()})

    @app.route("/api/premium_discipline/portfolio/replay/run", methods=["POST"])
    def premium_discipline_portfolio_replay_run():
        if get_intraday_bars is None: return jsonify({"ok": False, "error": "Intraday bar provider is unavailable."}), 503
        result = replay_due_portfolios(portfolio_outcomes, get_intraday_bars)
        return jsonify({"ok": True, "run": result, "scorecard": portfolio_outcomes.scorecard()})

    @app.route("/api/premium_discipline/portfolio/calibration")
    def premium_discipline_portfolio_calibration():
        return jsonify({"ok": True, "active_policy": portfolio_calibration.active_policy(), "runs": portfolio_calibration.recent(limit=20)})

    @app.route("/api/premium_discipline/portfolio/calibration/run", methods=["POST"])
    def premium_discipline_portfolio_calibration_run():
        payload=request.get_json(silent=True) or {}
        try: result=portfolio_calibration.run(min_sample=max(5,int(payload.get("min_sample",20))),lookback=max(1,int(payload.get("lookback",500))))
        except (TypeError,ValueError): return jsonify({"ok":False,"error":"min_sample and lookback must be integers."}),400
        return jsonify({"ok":True,"calibration":result})

    @app.route("/api/premium_discipline/portfolio/calibration/promote", methods=["POST"])
    def premium_discipline_portfolio_calibration_promote():
        payload=request.get_json(silent=True) or {}
        try: result=portfolio_calibration.promote(int(payload.get("run_id")),str(payload.get("promoted_by") or "operator")[:120])
        except (TypeError,ValueError) as exc: return jsonify({"ok":False,"error":str(exc)}),409
        return jsonify({"ok":True,"promotion":result})

    @app.route("/api/premium_discipline/expectancy/grade", methods=["POST"])
    def premium_discipline_expectancy_grade():
        payload = request.get_json(silent=True) or {}
        try:
            row_id = int(payload.get("row_id"))
            pnl = float(payload.get("pnl"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "row_id and numeric pnl are required."}), 400
        outcome = str(payload.get("outcome") or ("WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"))[:40]
        ok = expectancy.grade(row_id, outcome=outcome, pnl=pnl, source=str(payload.get("source") or "OPERATOR")[:40])
        return jsonify({"ok": ok, "row_id": row_id})

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


    @app.route("/api/premium_discipline/execution-reality")
    def premium_discipline_execution_reality():
        ticker = (request.args.get("ticker") or "SPX").upper()
        model = (request.args.get("model") or "MID_MINUS_ONE_TICK").upper()
        lr = (last_result_provider() or {}) if last_result_provider else {}
        now = dt.datetime.now(ET)
        policy = calibration.active_policy()
        exp = build_expectancy_intelligence(lr, store=expectancy, ticker=ticker, chain_fetcher=chain_fetcher, now_et=now, expiration=now.date().isoformat(), threshold=policy.get("threshold"), weights=policy.get("weights"))
        result = build_execution_reality(exp, model=model)
        record = execution_reality_store.record_shadow(ticker, result["recommendation"], observed_at=now) if result.get("recommendation") else None
        return jsonify({"ok": True, "ticker": ticker, "execution_reality": result, "record": record})

    @app.route("/api/premium_discipline/execution-reality/scorecard")
    def premium_discipline_execution_reality_scorecard():
        try: limit = max(1, min(int(request.args.get("limit") or 100), 500))
        except ValueError: limit = 100
        return jsonify({"ok": True, "scorecard": execution_reality_store.scorecard(), "records": execution_reality_store.recent(limit)})

    @app.route("/api/premium_discipline/execution-reality/shadow-fill", methods=["POST"])
    def premium_discipline_execution_reality_shadow_fill():
        payload = request.get_json(silent=True) or {}
        ticker = str(payload.get("ticker") or "SPX").upper()
        candidate = payload.get("candidate")
        if candidate:
            result = evaluate_candidate_execution(candidate, model=str(payload.get("model") or "MID_MINUS_ONE_TICK"))
        else:
            lr = (last_result_provider() or {}) if last_result_provider else {}
            now = dt.datetime.now(ET)
            policy = calibration.active_policy()
            exp = build_expectancy_intelligence(lr, store=expectancy, ticker=ticker, chain_fetcher=chain_fetcher, now_et=now, expiration=now.date().isoformat(), threshold=policy.get("threshold"), weights=policy.get("weights"))
            reality = build_execution_reality(exp, model=str(payload.get("model") or "MID_MINUS_ONE_TICK"))
            result = reality.get("recommendation")
            if result is None:
                return jsonify({"ok": False, "error": "No executable candidate is available for shadow fill."}), 409
        record = execution_reality_store.record_shadow(ticker, result)
        return jsonify({"ok": True, "shadow_fill": result, "record": record})

    @app.route("/api/premium_discipline/execution-reality/actual-fill", methods=["POST"])
    def premium_discipline_execution_reality_actual_fill():
        payload = request.get_json(silent=True) or {}
        try:
            execution_id = int(payload.get("execution_id"))
            actual_fill_credit = float(payload.get("actual_fill_credit"))
            latency = int(payload["fill_latency_ms"]) if payload.get("fill_latency_ms") is not None else None
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "execution_id and actual_fill_credit are required numeric values."}), 400
        try:
            record = execution_reality_store.record_actual(execution_id, actual_fill_credit=actual_fill_credit, fill_latency_ms=latency, details=payload.get("details") or {})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 404
        return jsonify({"ok": True, "actual_fill": record, "scorecard": execution_reality_store.scorecard()})

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


    @app.route("/api/premium_discipline/risk-governor")
    def premium_discipline_risk_governor():
        ticker=(request.args.get("ticker") or "SPX").upper(); lr=(last_result_provider() or {}) if last_result_provider else {}; now=dt.datetime.now(ET); policy=calibration.active_policy()
        exp=build_expectancy_intelligence(lr,store=expectancy,ticker=ticker,chain_fetcher=chain_fetcher,now_et=now,expiration=now.date().isoformat(),threshold=policy.get("threshold"),weights=policy.get("weights"))
        portfolio=build_portfolio_optimizer(exp,daily_realized_pnl=float(request.args.get("daily_pnl") or 0),open_risk=float(request.args.get("open_risk") or 0),account_size=float(request.args["account_size"]) if request.args.get("account_size") else None,allocation_policy=portfolio_calibration.active_policy())
        reality=build_execution_reality(exp); risk=evaluate_portfolio_risk(portfolio,reality,daily_realized_pnl=float(request.args.get("daily_pnl") or 0),open_risk=float(request.args.get("open_risk") or 0),trades_today=int(request.args.get("trades_today") or 0),losses_today=int(request.args.get("losses_today") or 0),account_size=float(request.args["account_size"]) if request.args.get("account_size") else None)
        return jsonify({"ok":True,"ticker":ticker,"risk_governor":risk,"record":risk_governor_store.record(ticker,risk,observed_at=now)})

    @app.route("/api/premium_discipline/execution-orchestrator/intents", methods=["GET","POST"])
    def premium_execution_intents():
        if request.method=="GET": return jsonify({"ok":True,"intents":execution_orchestrator.recent(int(request.args.get("limit") or 100))})
        p=request.get_json(silent=True) or {}; return jsonify(execution_orchestrator.create_intent(str(p.get("ticker") or "SPX"),p.get("portfolio") or {},p.get("risk_governor") or {},p.get("execution_reality") or {},p.get("idempotency_key")))

    @app.route("/api/premium_discipline/execution-orchestrator/preview", methods=["POST"])
    def premium_execution_preview():
        p=request.get_json(silent=True) or {}; return jsonify(execution_orchestrator.preview(str(p.get("intent_id") or ""),int(p.get("ttl_seconds") or 120)))

    @app.route("/api/premium_discipline/execution-orchestrator/confirm", methods=["POST"])
    def premium_execution_confirm():
        p=request.get_json(silent=True) or {}; return jsonify(execution_orchestrator.confirm(str(p.get("intent_id") or ""),str(p.get("confirmed_by") or ""),bool(p.get("acknowledgement")),int(p.get("ttl_seconds") or 90)))

    @app.route("/api/premium_discipline/execution-orchestrator/submit", methods=["POST"])
    def premium_execution_submit():
        p=request.get_json(silent=True) or {}; result=execution_orchestrator.submit(str(p.get("intent_id") or ""),str(p.get("confirmation_id") or ""),p.get("revalidation") or {})
        return jsonify(result), (200 if result.get("ok") else 409)

    @app.route("/api/premium_discipline/learning")
    def premium_discipline_learning():
        ticker=(request.args.get("ticker") or "SPX").upper()
        lr=(last_result_provider() or {}) if last_result_provider else {}
        context={"ticker":ticker,"premium_regime":lr.get("premium_regime") or lr.get("regime"),"direction":lr.get("direction") or lr.get("bias"),"auction_state":lr.get("auction_state"),"gamma_regime":lr.get("gamma_regime"),"vix_regime":lr.get("vix_regime")}
        try:min_sample=max(5,int(request.args.get("min_sample") or 20))
        except ValueError:return jsonify({"ok":False,"error":"min_sample must be an integer."}),400
        return jsonify({"ok":True,"ticker":ticker,"institutional_learning":build_learning_intelligence(learning_store,context,min_sample=min_sample)})

    @app.route("/api/premium_discipline/learning/samples", methods=["GET","POST"])
    def premium_discipline_learning_samples():
        if request.method=="GET":
            return jsonify({"ok":True,"samples":learning_store.recent(int(request.args.get("limit") or 100))})
        p=request.get_json(silent=True) or {}
        if not p.get("strategy"): return jsonify({"ok":False,"error":"strategy is required."}),400
        rec=learning_store.record(str(p.get("ticker") or "SPX"),str(p["strategy"]),p.get("context") or {},outcome=p.get("outcome"),pnl=p.get("pnl"),source=str(p.get("source") or "SYSTEM"))
        return jsonify({"ok":True,"sample":rec})

    @app.route("/api/premium_discipline/learning/grade", methods=["POST"])
    def premium_discipline_learning_grade():
        p=request.get_json(silent=True) or {}
        try: ok=learning_store.grade(int(p.get("row_id")),str(p.get("outcome") or "UNKNOWN"),float(p.get("pnl")),str(p.get("source") or "OPERATOR"))
        except (TypeError,ValueError): return jsonify({"ok":False,"error":"row_id and numeric pnl are required."}),400
        return jsonify({"ok":ok})

    @app.route("/api/premium_discipline/decision-narrative")
    def premium_discipline_decision_narrative():
        ticker=(request.args.get("ticker") or "SPX").upper(); lr=(last_result_provider() or {}) if last_result_provider else {}; now=dt.datetime.now(ET); policy=calibration.active_policy()
        current=snapshot(ticker); intel=rank_premium_strategies(lr,chain_fetcher=chain_fetcher,now_et=now,symbol=ticker,expiration=now.date().isoformat(),threshold=policy.get("threshold"),weights=policy.get("weights")); exp=build_expectancy_intelligence(lr,store=expectancy,ticker=ticker,chain_fetcher=chain_fetcher,now_et=now,expiration=now.date().isoformat(),threshold=policy.get("threshold"),weights=policy.get("weights")); portfolio=build_portfolio_optimizer(exp,allocation_policy=portfolio_calibration.active_policy()); execution=build_execution_reality(exp); risk=evaluate_portfolio_risk(portfolio,execution); learning=build_learning_intelligence(learning_store,{"ticker":ticker,"premium_regime":intel.get("regime"),"direction":intel.get("direction")})
        narrative=build_decision_narrative(eligibility=current.get("eligibility") or {},intelligence=intel,portfolio=portfolio,execution=execution,risk=risk,learning=learning)
        return jsonify({"ok":True,"ticker":ticker,"decision_narrative":narrative})

    @app.route("/api/premium_discipline/trade-lifecycle", methods=["GET","POST"])
    def premium_discipline_trade_lifecycle():
        if request.method=="GET": return jsonify({"ok":True,"events":lifecycle_store.recent(int(request.args.get("limit") or 100))})
        p=request.get_json(silent=True) or {}; position=p.get("position") or {}; market=p.get("market") or {}
        if not position: return jsonify({"ok":False,"error":"position is required."}),400
        result=evaluate_trade_lifecycle(position,market); record=lifecycle_store.record(result["position_id"],result)
        return jsonify({"ok":True,"trade_lifecycle":result,"record":record})

