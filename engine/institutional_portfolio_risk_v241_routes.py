"""HTTP routes for APEX 24.1 Institutional Portfolio & Risk Intelligence.

All routes are read-only / advisory. POST routes accept a snapshot body and
return a computed assessment; they never persist, submit, or mutate orders.
"""
from flask import jsonify, request

from .institutional_portfolio_risk_v241 import (
    build_portfolio_intelligence,
    capital_allocation,
    evaluate_portfolio,
    prioritize_opportunities,
    resolve_risk_budget,
    status,
)

# Canonical portfolio-risk surface owned by APEX 24.1. Startup verifies these
# are registered and fails loudly otherwise (no silent registration failures).
REQUIRED_ROUTES = (
    ("GET", "/api/portfolio-risk/status"),
    ("GET", "/api/portfolio-risk/exposure"),
    ("GET", "/api/portfolio-risk/budget"),
    ("GET", "/api/portfolio-risk/opportunities"),
    ("POST", "/api/portfolio-risk/evaluate"),
    ("POST", "/api/portfolio-risk/allocation"),
)


def verify_registered(app) -> list[str]:
    """Return the list of REQUIRED_ROUTES missing from ``app``'s URL map."""
    present = {(m, str(rule)) for rule in app.url_map.iter_rules()
               for m in (rule.methods or set())}
    missing = []
    for method, path in REQUIRED_ROUTES:
        if (method, path) not in present:
            missing.append(f"{method} {path}")
    return missing


def register_institutional_portfolio_risk_v241_routes(app, *, last_result_provider=None):
    def last():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get('/api/portfolio-risk/status')
    def portfolio_risk_status():
        return jsonify(status())

    @app.get('/api/portfolio-risk/exposure')
    def portfolio_risk_exposure():
        result = build_portfolio_intelligence(last())
        return jsonify({'ok': True, 'version': result['version'],
                        'portfolio_state': result['portfolio_state'],
                        'exposure': result['exposure'],
                        'base_assessment': result['base_assessment']})

    @app.get('/api/portfolio-risk/budget')
    def portfolio_risk_budget():
        result = build_portfolio_intelligence(last())
        return jsonify({'ok': True, 'version': result['version'],
                        'risk_budget': result['risk_budget'],
                        'budget_manager': result['budget_manager']})

    @app.get('/api/portfolio-risk/opportunities')
    def portfolio_risk_opportunities():
        result = build_portfolio_intelligence(last())
        return jsonify({'ok': True, 'version': result['version'],
                        'opportunities': result.get('opportunities', {'ranked': [], 'count': 0})})

    @app.post('/api/portfolio-risk/evaluate')
    def portfolio_risk_evaluate():
        body = request.get_json(silent=True) or {}
        # Backward-compatible with the 16.3 contract: accept either a raw
        # snapshot or a {"snapshot": {...}} envelope.
        snapshot = body.get('snapshot') if isinstance(body.get('snapshot'), dict) else body
        return jsonify(evaluate_portfolio(snapshot))

    @app.post('/api/portfolio-risk/allocation')
    def portfolio_risk_allocation():
        body = request.get_json(silent=True) or {}
        snapshot = body.get('snapshot') if isinstance(body.get('snapshot'), dict) else body
        evaluation = evaluate_portfolio(snapshot)
        allocation = capital_allocation(
            assessment={'risk_state': evaluation['base_assessment']['risk_state']},
            exposure=evaluation['exposure'],
            budget_eval=evaluation['budget_manager'],
            signal=snapshot.get('signal'),
            budget=evaluation['risk_budget'],
        )
        return jsonify({'ok': True, 'version': evaluation['version'],
                        'capital_allocation': allocation,
                        'portfolio_state': evaluation['portfolio_state']})

    @app.post('/api/portfolio-risk/prioritize')
    def portfolio_risk_prioritize():
        body = request.get_json(silent=True) or {}
        opportunities = body.get('opportunities') or []
        current_book = body.get('positions') or []
        return jsonify({'ok': True,
                        'result': prioritize_opportunities(opportunities, current_book=current_book)})
