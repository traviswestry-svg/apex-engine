"""HTTP routes for the APEX 26.1-26.5 execution intelligence suite.

All routes are advisory and order-free. Registers:
  26.1 Entry Optimization   /api/entry-optimization/*
  26.2 Contract Intelligence /api/contract-intelligence/*
  26.3 Liquidity & Slippage  /api/liquidity/*
  26.4 Position Sizing       /api/position-sizing/*
  26.5 Dynamic Trade Mgmt    /api/trade-management/*
"""
from flask import jsonify, request

from . import entry_optimization_v261 as entry_opt
from . import contract_intelligence_v262 as contract_intel
from . import liquidity_slippage_v263 as liquidity
from . import position_sizing_v264 as sizing
from . import dynamic_trade_management_v265 as management

REQUIRED_ROUTES = (
    ("GET", "/api/entry-optimization/status"),
    ("GET", "/api/entry-optimization/current"),
    ("POST", "/api/entry-optimization/evaluate"),
    ("GET", "/api/contract-intelligence/status"),
    ("GET", "/api/contract-intelligence/current"),
    ("POST", "/api/contract-intelligence/evaluate"),
    ("GET", "/api/liquidity/status"),
    ("GET", "/api/liquidity/current"),
    ("POST", "/api/liquidity/evaluate"),
    ("GET", "/api/position-sizing/status"),
    ("POST", "/api/position-sizing/size"),
    ("GET", "/api/trade-management/status"),
    ("GET", "/api/trade-management/current"),
    ("POST", "/api/trade-management/evaluate"),
)


def verify_registered(app):
    present = {(method, str(rule)) for rule in app.url_map.iter_rules() for method in (rule.methods or set())}
    return [f"{method} {path}" for method, path in REQUIRED_ROUTES if (method, path) not in present]


def _json_or_400():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify({"ok": False, "status": "INVALID_REQUEST",
                               "message": "JSON object required."}), 400)
    return payload, None


def register_execution_suite_v26x_routes(app, *, last_result_provider=None):
    def current_payload():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    def _contracts(payload):
        try:
            return max(1, int(payload.get("contracts", 1)))
        except (TypeError, ValueError):
            return 1

    # 26.1 Entry Optimization
    @app.get("/api/entry-optimization/status")
    def entry_opt_status():
        return jsonify(entry_opt.status())

    @app.get("/api/entry-optimization/current")
    def entry_opt_current():
        return jsonify(entry_opt.optimize(current_payload()))

    @app.post("/api/entry-optimization/evaluate")
    def entry_opt_evaluate():
        payload, err = _json_or_400()
        if err:
            return err
        return jsonify(entry_opt.optimize(payload, contracts=_contracts(payload)))

    # 26.2 Contract Intelligence
    @app.get("/api/contract-intelligence/status")
    def contract_intel_status():
        return jsonify(contract_intel.status())

    @app.get("/api/contract-intelligence/current")
    def contract_intel_current():
        return jsonify(contract_intel.recommend(current_payload()))

    @app.post("/api/contract-intelligence/evaluate")
    def contract_intel_evaluate():
        payload, err = _json_or_400()
        if err:
            return err
        return jsonify(contract_intel.recommend(payload, contracts=_contracts(payload)))

    # 26.3 Liquidity & Slippage
    @app.get("/api/liquidity/status")
    def liquidity_status():
        return jsonify(liquidity.status())

    @app.get("/api/liquidity/current")
    def liquidity_current():
        return jsonify(liquidity.analyze(current_payload()))

    @app.post("/api/liquidity/evaluate")
    def liquidity_evaluate():
        payload, err = _json_or_400()
        if err:
            return err
        return jsonify(liquidity.analyze(payload, contracts=_contracts(payload)))

    # 26.4 Position Sizing
    @app.get("/api/position-sizing/status")
    def sizing_status():
        return jsonify(sizing.status())

    @app.post("/api/position-sizing/size")
    def sizing_size():
        payload, err = _json_or_400()
        if err:
            return err
        return jsonify(sizing.size(
            payload,
            entry_premium=payload.get("entry_premium"),
            stop_premium=payload.get("stop_premium"),
            confidence=payload.get("confidence"),
            reward_risk=payload.get("reward_risk"),
        ))

    # 26.5 Dynamic Trade Management
    @app.get("/api/trade-management/status")
    def management_status():
        return jsonify(management.status())

    @app.get("/api/trade-management/current")
    def management_current():
        return jsonify(management.manage(current_payload()))

    @app.post("/api/trade-management/evaluate")
    def management_evaluate():
        payload, err = _json_or_400()
        if err:
            return err
        return jsonify(management.manage(payload))
