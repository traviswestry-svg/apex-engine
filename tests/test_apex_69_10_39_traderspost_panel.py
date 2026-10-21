"""Read-only TradersPost panel regression checks."""
import sqlite3
from pathlib import Path

from engine.execution.traderspost_paper import panel_summary, connect


def test_panel_missing_ledger_does_not_create_file(tmp_path):
    path = tmp_path / 'missing.db'
    data = panel_summary(db_path=path)
    assert data['ready_for_unattended_orders'] is False
    assert data['fill_confirmation_supported'] is False
    assert data['ledger_state'] == 'NOT_INITIALIZED'
    assert not path.exists()
    assert 'APEX_TRADERSPOST_WEBHOOK_URL' not in str(data)


def test_panel_redacts_payload_and_never_claims_fills(tmp_path):
    path = tmp_path / 'paper.db'
    with connect(path) as db:
        db.execute('INSERT INTO paper_signals (signal_id, created_at, status, payload_json, decision_id) VALUES (?,?,?,?,?)',
                   ('s1','2026-10-21T15:00:00+00:00','WEBHOOK_ACCEPTED_UNCONFIRMED',
                    '{"secret":"never_show"}','private-decision'))
    data = panel_summary(db_path=path)
    assert data['ledger_state'] == 'AVAILABLE'
    assert data['recent_signals'][0]['fill_confirmed'] is False
    assert 'never_show' not in str(data)
    assert 'private-decision' not in str(data)


def test_routes_are_read_only_and_panel_has_no_order_controls():
    source = Path('engine/execution/trade_routes.py').read_text()
    assert '@app.route("/api/paper/traderspost/panel-summary", methods=["GET"])' in source
    assert '@app.route("/apex_os/traderspost", methods=["GET"])' in source
    template = Path('templates/traderspost_paper_panel.html').read_text()
    assert 'method:\'GET\'' in template
    assert '/api/paper/traderspost/dispatch' not in template
    assert '/api/paper/traderspost/connectivity-test' not in template


def test_app_session_gate_contract():
    auth = Path('engine/auth.py').read_text()
    assert 'EXEMPT_PREFIXES = ("/static/",)' in auth
    assert '/apex_os/traderspost' not in auth
    assert '/api/paper/traderspost/panel-summary' not in auth
