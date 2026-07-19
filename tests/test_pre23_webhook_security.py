import importlib
import os
import sys


def _load_app(monkeypatch, secret=None):
    monkeypatch.setenv('RUN_SCANNER_ON_IMPORT', 'false')
    monkeypatch.setenv('DISABLE_BACKGROUND_SCANNER', 'true')
    if secret is None:
        for name in ('TV_WEBHOOK_SECRET','WEBHOOK_SECRET','TRADINGVIEW_SECRET'):
            monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv('TV_WEBHOOK_SECRET', secret)
    sys.modules.pop('app', None)
    return importlib.import_module('app')


def test_webhook_fails_closed_without_secret(monkeypatch):
    module = _load_app(monkeypatch)
    response = module.app.test_client().post('/tv_signal', json={'secret':'tv_institutional_signal','ticker':'SPX'})
    assert response.status_code == 503


def test_webhook_rejects_wrong_secret(monkeypatch):
    module = _load_app(monkeypatch, 'configured-secret')
    response = module.app.test_client().post('/tv_signal', json={'secret':'wrong','ticker':'SPX'})
    assert response.status_code == 403
