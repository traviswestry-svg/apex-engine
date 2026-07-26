"""Tests for engine/auth.py — the application-wide access gate.

These tests set APEX_AUTH_ENFORCE=true to activate the gate inside pytest
(where it otherwise stands down so the legacy suite keeps working uncredentialed).
"""
from __future__ import annotations

import importlib

import pytest

TOKEN = "test-token-0123456789abcdef"


def _fresh_app(monkeypatch, token=TOKEN, enforce=True):
    if token is None:
        monkeypatch.delenv("APEX_AUTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("APEX_AUTH_TOKEN", token)
    monkeypatch.setenv("APEX_AUTH_ENFORCE", "true" if enforce else "false")
    monkeypatch.setenv("APEX_COOKIE_SECURE", "false")  # http test client

    from flask import Flask, jsonify
    import engine.auth as auth
    importlib.reload(auth)

    app = Flask(__name__)
    auth.install_auth(app)

    @app.route("/health")
    def health():
        return jsonify({"ok": True})

    @app.route("/api/trade/spx/place-entry", methods=["POST"])
    def place_entry():
        return jsonify({"ok": True, "placed": True})

    @app.route("/apex_os")
    def dashboard():
        return "<html>dashboard</html>"

    @app.route("/tv_signal", methods=["POST"])
    def tv_signal():
        return jsonify({"ok": True, "webhook": True})

    return app, auth


def test_unauthenticated_api_request_is_401(monkeypatch):
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    r = c.post("/api/trade/spx/place-entry", json={"confirmed": True})
    assert r.status_code == 401
    assert r.get_json()["error"] == "unauthorized"


def test_header_token_x_apex_key_allows(monkeypatch):
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    r = c.post("/api/trade/spx/place-entry", json={}, headers={"X-APEX-KEY": TOKEN})
    assert r.status_code == 200
    assert r.get_json()["placed"] is True


def test_bearer_token_allows(monkeypatch):
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    r = c.post("/api/trade/spx/place-entry", json={},
               headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


def test_wrong_header_token_denied(monkeypatch):
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    r = c.post("/api/trade/spx/place-entry", json={}, headers={"X-APEX-KEY": "nope"})
    assert r.status_code == 401


def test_browser_get_redirects_to_login(monkeypatch):
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    r = c.get("/apex_os", headers={"Accept": "text/html"})
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_login_sets_session_cookie_and_dashboard_loads(monkeypatch):
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    r = c.post("/login?next=/apex_os", data={"token": TOKEN})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/apex_os")
    r2 = c.get("/apex_os", headers={"Accept": "text/html"})
    assert r2.status_code == 200
    # and API fetches ride the same cookie (what the dashboard JS does)
    r3 = c.post("/api/trade/spx/place-entry", json={})
    assert r3.status_code == 200


def test_bad_login_rejected_and_lockout_after_five(monkeypatch):
    app, auth = _fresh_app(monkeypatch)
    c = app.test_client()
    for _ in range(auth.MAX_FAILED_ATTEMPTS):
        r = c.post("/login", data={"token": "wrong"})
        assert r.status_code == 401
    r = c.post("/login", data={"token": TOKEN})  # even the right token now
    assert r.status_code == 429


def test_health_exempt(monkeypatch):
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    assert c.get("/health").status_code == 200


def test_tv_signal_exempt_from_gate(monkeypatch):
    # It carries its own HMAC secret check inside the route.
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    assert c.post("/tv_signal", json={}).status_code == 200


def test_missing_token_fails_closed_503(monkeypatch):
    app, _ = _fresh_app(monkeypatch, token=None)
    c = app.test_client()
    r = c.post("/api/trade/spx/place-entry", json={})
    assert r.status_code == 503
    assert "APEX_AUTH_TOKEN" in r.get_json()["detail"]
    # health still reachable for Render
    assert c.get("/health").status_code == 200


def test_logout_clears_session(monkeypatch):
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    c.post("/login", data={"token": TOKEN})
    assert c.post("/api/trade/spx/place-entry", json={}).status_code == 200
    c.get("/logout")
    assert c.post("/api/trade/spx/place-entry", json={}).status_code == 401


def test_next_redirect_sanitized(monkeypatch):
    app, _ = _fresh_app(monkeypatch)
    c = app.test_client()
    r = c.post("/login?next=https://evil.example.com", data={"token": TOKEN})
    assert r.status_code == 302
    assert "evil" not in r.headers["Location"]
    r2 = c.post("/login?next=//evil.example.com", data={"token": TOKEN})
    assert "evil" not in r2.headers["Location"]


def test_gate_stands_down_in_pytest_without_enforce(monkeypatch):
    # This is what keeps the legacy ~1,500-test suite green uncredentialed.
    app, _ = _fresh_app(monkeypatch, enforce=False)
    c = app.test_client()
    assert c.post("/api/trade/spx/place-entry", json={}).status_code == 200
