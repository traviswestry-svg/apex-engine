from pathlib import Path

from engine import institutional_trading_desk_ux as ux


def test_status_is_read_only_and_confirmation_gated():
    s = ux.status()
    assert s["status"] == "READY"
    assert s["read_only"] is True
    assert s["automatic_order_submission_enabled"] is False
    assert s["human_confirmation_required"] is True


def test_decision_ribbon_has_eight_desk_states():
    mission = {
        "market_state": {"active_state": "BALANCED"},
        "institutional_pressure": {"bias": "BULLISH", "institutional_pressure_score": 81},
        "playbook": {"active_playbook": "OPENING_DRIVE"},
        "institutional_confluence": {"institutional_confluence_score": 88},
        "portfolio_risk": {"risk_state": "NORMAL"},
        "live_operations": {"tradeability": "TRADEABLE"},
    }
    broker = {"latest": {"sync_state": "SYNCED"}}
    ribbon = ux._decision_ribbon(mission, broker)
    assert len(ribbon) == 8
    assert ribbon[0]["value"] == "BALANCED"
    assert ribbon[-1]["value"] == "BLOCKED"


def test_evidence_fallback_is_explicitly_unavailable():
    rows = ux._evidence({})
    assert len(rows) >= 7
    assert all(row["available"] is False for row in rows)
    assert all(row["score"] == 0 for row in rows)


def test_workspace_degrades_without_crashing(monkeypatch):
    monkeypatch.setattr(ux.lmc, "dashboard", lambda symbol: {"status": "READY"})
    monkeypatch.setattr(ux.iad, "dashboard", lambda limit: {"active_trades": [], "recent_trades": []})
    monkeypatch.setattr(ux.bsps, "dashboard", lambda account, broker: {"latest": {}})
    monkeypatch.setattr(ux.pi, "dashboard", lambda symbol: {"analysis": {}})
    result = ux.workspace("spx")
    assert result["ok"] is True
    assert result["symbol"] == "SPX"
    assert len(result["ribbon"]) == 8
    assert result["trade_timeline"] == []


def test_template_contains_17_1_workstation_features():
    root = Path(__file__).parents[1]
    html = (root / "templates" / "institutional_trading_desk.html").read_text()
    for term in ("Decision", "Evidence Explorer", "Trade Lifecycle Timeline", "Broker Health Center", "Explainable Intelligence", "Command"):
        assert term in html
    assert "localStorage" in html
    assert "automatic broker submission remains disabled" in html.lower()


def test_routes_register_workspace_endpoints():
    root = Path(__file__).parents[1]
    routes = (root / "engine" / "institutional_roadmap_routes.py").read_text()
    assert "/api/trading-desk-ux/status" in routes
    assert "/api/trading-desk-ux/workspace" in routes
    assert "institutional_trading_desk_ux" in routes
