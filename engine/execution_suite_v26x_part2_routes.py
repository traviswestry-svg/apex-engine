"""HTTP routes for the APEX 26.6-26.10 execution intelligence suite (part 2).

All routes are advisory/read-only. Registers:
  26.6  Trade Story        /api/trade-story/*
  26.7  Broker Intelligence /api/broker-intelligence/*   (preview/read-only)
  26.8  Execution Review   /api/execution-review/*
  26.9  Command Center     /api/command-center/*
  26.10 Trader Mode        /api/trader-mode/*
"""
from flask import jsonify, request

from . import trade_story_v266 as trade_story
from . import broker_intelligence_v267 as broker
from . import execution_review_v268 as exec_review
from . import command_center_v269 as command_center

REQUIRED_ROUTES = (
    ("GET", "/api/trade-story/status"),
    ("GET", "/api/trade-story/current"),
    ("POST", "/api/trade-story/evaluate"),
    ("GET", "/api/broker-intelligence/status"),
    ("GET", "/api/broker-intelligence/current"),
    ("POST", "/api/broker-intelligence/preview"),
    ("GET", "/api/execution-review/status"),
    ("POST", "/api/execution-review/evaluate"),
    ("GET", "/api/command-center/status"),
    ("GET", "/api/command-center/current"),
    ("GET", "/api/trader-mode/current"),
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


def register_execution_suite_v26x_part2_routes(app, *, last_result_provider=None):
    def current_payload():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    # 26.6 Trade Story
    @app.get("/api/trade-story/status")
    def trade_story_status():
        return jsonify(trade_story.status())

    @app.get("/api/trade-story/current")
    def trade_story_current():
        return jsonify(trade_story.build_story(current_payload()))

    @app.post("/api/trade-story/evaluate")
    def trade_story_evaluate():
        payload, err = _json_or_400()
        if err:
            return err
        return jsonify(trade_story.build_story(payload))

    # 26.7 Broker Intelligence (preview/read-only)
    @app.get("/api/broker-intelligence/status")
    def broker_status():
        return jsonify(broker.status())

    @app.get("/api/broker-intelligence/current")
    def broker_current():
        return jsonify(broker.build_broker_view(current_payload()))

    @app.post("/api/broker-intelligence/preview")
    def broker_preview():
        payload, err = _json_or_400()
        if err:
            return err
        # Normalizes a supplied preview only; never fetches or places an order.
        return jsonify(broker.build_broker_view(payload))

    # 26.8 Execution Review
    @app.get("/api/execution-review/status")
    def exec_review_status():
        return jsonify(exec_review.status())

    @app.post("/api/execution-review/evaluate")
    def exec_review_evaluate():
        payload, err = _json_or_400()
        if err:
            return err
        trade = payload.get("trade") if isinstance(payload.get("trade"), dict) else payload
        return jsonify(exec_review.review(trade))

    # 26.9 Command Center
    @app.get("/api/command-center/status")
    def command_center_status():
        return jsonify(command_center.status())

    @app.get("/api/command-center/current")
    def command_center_current():
        return jsonify(command_center.build_command_center(current_payload()))

    # 26.10 Trader Mode
    @app.get("/api/trader-mode/current")
    def trader_mode_current():
        return jsonify(command_center.build_trader_mode(current_payload()))
