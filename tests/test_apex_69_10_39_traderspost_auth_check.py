"""Read-only TradersPost auth probe, including regressions against order dispatch."""
import pytest

flask = pytest.importorskip('flask')


def app_for_routes(monkeypatch):
    from engine.execution import trade_routes
    app = flask.Flask(__name__)
    # Avoid network-capable chain providers during route registration.
    class FakeBus:
        def register(self, *args, **kwargs):
            pass
    monkeypatch.setattr(trade_routes, '_bus', lambda: FakeBus())
    trade_routes.register_trade_routes(app)
    return app


def test_auth_check_rejects_absent_weak_and_incorrect_tokens(monkeypatch):
    app = app_for_routes(monkeypatch)
    client = app.test_client()
    monkeypatch.delenv('APEX_TRADERSPOST_OPERATOR_TOKEN', raising=False)
    assert client.get('/api/paper/traderspost/auth-check').status_code == 403
    monkeypatch.setenv('APEX_TRADERSPOST_OPERATOR_TOKEN','short')
    assert client.get('/api/paper/traderspost/auth-check', headers={'X-APEX-Paper-Token':'short'}).status_code == 403
    monkeypatch.setenv('APEX_TRADERSPOST_OPERATOR_TOKEN','A'*32)
    response = client.get('/api/paper/traderspost/auth-check', headers={'X-APEX-Paper-Token':'wrong'})
    assert response.status_code == 403
    assert response.get_json() == {'ok':False, 'authorized':False}


def test_auth_check_valid_is_read_only_and_does_not_leak_token(monkeypatch):
    app = app_for_routes(monkeypatch)
    token = 'test_secret_operator_token_1234567890'
    monkeypatch.setenv('APEX_TRADERSPOST_OPERATOR_TOKEN',token)
    monkeypatch.setenv('APEX_TRADERSPOST_MODE','paper')
    monkeypatch.setenv('APEX_TRADERSPOST_SEND_ENABLED','true')
    from engine.execution import traderspost_paper
    def fail_dispatch(*args, **kwargs):
        raise AssertionError('auth-check must not dispatch trades')
    monkeypatch.setattr(traderspost_paper,'dispatch',fail_dispatch)
    response=app.test_client().get('/api/paper/traderspost/auth-check',headers={'X-APEX-Paper-Token':token})
    assert response.status_code == 200
    assert response.get_json() == {'ok':True,'authorized':True,'mode':'paper','send_enabled':True}
    assert token not in response.get_data(as_text=True)
    assert app.test_client().post('/api/paper/traderspost/auth-check',headers={'X-APEX-Paper-Token':token}).status_code == 405


def test_dispatch_still_rejects_incorrect_operator_token(monkeypatch):
    app=app_for_routes(monkeypatch)
    monkeypatch.setenv('APEX_TRADERSPOST_OPERATOR_TOKEN','B'*32)
    response=app.test_client().post('/api/paper/traderspost/dispatch',json={},headers={'X-APEX-Paper-Token':'bad'})
    assert response.status_code == 403
