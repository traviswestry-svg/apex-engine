"""Paper-only readiness and no-order webhook regression tests."""
import json
import pytest
from engine.execution import traderspost_paper as tp


def configure(monkeypatch):
    for k,v in {'APEX_TRADERSPOST_MODE':'paper',
                'APEX_TRADERSPOST_PAPER_CONFIRMED':'true',
                'APEX_TRADERSPOST_SEND_ENABLED':'true',
                'APEX_TRADERSPOST_OPERATOR_TOKEN':'T'*64,
                'APEX_TRADERSPOST_WEBHOOK_URL':'https://webhooks.traderspost.io/trading/webhook/uuid/password',
                'APEX_LIVE_ORDER_ROUTING_ENABLED':'false'}.items():
        monkeypatch.setenv(k,v)


def test_readiness_redacted_and_never_claims_autonomous_ready(monkeypatch):
    configure(monkeypatch)
    r=tp.readiness()
    assert r['configuration']['paper_mode']
    assert r['ready_for_unattended_orders'] is False
    assert 'broker_fill_confirmation_unavailable' in r['blockers']
    assert 'password' not in json.dumps(r)
    assert 'TTTTTT' not in json.dumps(r)


def test_readiness_detects_disabled_and_invalid_url(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv('APEX_TRADERSPOST_WEBHOOK_URL','https://example.com/trading/webhook/uuid/password')
    assert tp.readiness()['configuration']['webhook_configured'] is False
    with pytest.raises(ValueError): tp.connectivity_test(sender=lambda x: (200,b'ok'))
    monkeypatch.setenv('APEX_TRADERSPOST_WEBHOOK_URL','https://webhooks.traderspost.io/trading/webhook/uuid/password')
    monkeypatch.setenv('APEX_LIVE_ORDER_ROUTING_ENABLED','true')
    with pytest.raises(ValueError): tp.connectivity_test(sender=lambda x: (200,b'ok'))


def test_test_payload_forces_true_no_order_and_does_not_dispatch(monkeypatch):
    configure(monkeypatch)
    def forbidden(*args,**kwargs):
        raise AssertionError('must not invoke trade dispatch')
    monkeypatch.setattr(tp,'dispatch', forbidden)
    sent=[]
    def sender(req):
        data=json.loads(req.data)
        sent.append(data)
        return 200,b'{"success":true}'
    result=tp.connectivity_test(sender=sender)
    assert result['status']=='TEST_WEBHOOK_ACCEPTED'
    assert result['orders_created'] is False and result['fill_confirmed'] is False
    assert len(sent)==1 and sent[0]['test'] is True
    assert sent[0]['ticker']=='SPX' and sent[0]['action']=='buy'
    assert 'quantity' not in sent[0]


def test_no_retry_when_send_uncertain(monkeypatch):
    configure(monkeypatch)
    called=[]
    def broken(req):
        called.append(req)
        raise TimeoutError('unknown delivery')
    result=tp.connectivity_test(sender=broken)
    assert result['status']=='DELIVERY_UNKNOWN' and len(called)==1


def test_readonly_route_and_post_requires_token(monkeypatch):
    flask=pytest.importorskip('flask')
    from engine.execution import trade_routes
    class FakeBus:
        def register(self,*args,**kwargs): pass
    monkeypatch.setattr(trade_routes,'_bus',lambda:FakeBus())
    app=flask.Flask(__name__)
    trade_routes.register_trade_routes(app)
    client=app.test_client()
    configure(monkeypatch)
    assert client.get('/api/paper/traderspost/readiness').status_code==403
    h={'X-APEX-Paper-Token':'T'*64}
    assert client.get('/api/paper/traderspost/readiness',headers=h).status_code==200
    assert client.get('/api/paper/traderspost/connectivity-test',headers=h).status_code==405
    assert client.post('/api/paper/traderspost/connectivity-test').status_code==403
    def fail_connectivity_test():
        raise ValueError('internal diagnostic')
    monkeypatch.setattr(tp,'connectivity_test',fail_connectivity_test)
    response=client.post('/api/paper/traderspost/connectivity-test',headers=h)
    assert response.status_code==400
    assert response.get_json()['error']=='invalid connectivity test request'
