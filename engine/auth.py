"""engine/auth.py — APEX access control layer.

WHAT THIS IS
------------
Application-wide shared-secret authentication. Every route is protected by a
single before_request gate except an explicit exemption list. Two ways in:

  1. Browser  : GET /login -> enter the token -> signed session cookie
                (Flask session; HttpOnly, SameSite=Lax, Secure by default).
                All same-origin fetch() calls in the dashboards then work
                unchanged because the cookie rides along automatically.
  2. API/CLI  : send the token on every request as either
                  X-APEX-KEY: <token>       or
                  Authorization: Bearer <token>

FAIL-CLOSED
-----------
If APEX_AUTH_TOKEN is not configured, every non-exempt route returns 503 with
an explanatory message. The app never silently runs open. (Mirrors the
trade_risk_guard philosophy: anything unexpected denies.)

EXEMPT PATHS
------------
  /health          Render health check must stay reachable.
  /login /logout   The gate itself.
  /static/*        CSS/JS needed to render the login page; nothing sensitive.
  /tv_signal       TradingView webhook — already guarded by its own HMAC
                   shared secret (TV_WEBHOOK_SECRET) inside the route.
  /favicon.ico     Browser noise.

TEST BYPASS
-----------
The existing suite (~1,500 tests) drives routes through test_client() without
credentials. Under pytest (PYTEST_CURRENT_TEST present) or app.testing, the
gate stands down UNLESS APEX_AUTH_ENFORCE=true — which is what the auth tests
themselves set to exercise the real gate. PYTEST_CURRENT_TEST never exists in
a production process, so production is always enforced.

ENV VARS
--------
  APEX_AUTH_TOKEN      the shared secret (required in production; >=16 chars
                       recommended — a short token logs a loud warning)
  APEX_SESSION_HOURS   browser session lifetime, default 12
  APEX_COOKIE_SECURE   default true; set false only for local http dev
  APEX_AUTH_ENFORCE    force enforcement even under pytest (used by tests)
  FLASK_SECRET_KEY     optional explicit cookie-signing key; otherwise derived
                       from APEX_AUTH_TOKEN (rotating the token logs out all
                       browsers — desired behavior)

Never raises into the caller: any unexpected error inside the gate denies.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from flask import Flask, jsonify, redirect, request, session

VERSION = "1.0.0_ACCESS_CONTROL"

# Paths that never require auth. Matched exactly, or by prefix for entries
# ending in "/".
EXEMPT_EXACT = {"/health", "/login", "/logout", "/favicon.ico", "/tv_signal"}
EXEMPT_PREFIXES = ("/static/",)

# Login brute-force guard (in-memory; single-worker deployment).
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60

_FAILED: Dict[str, Tuple[int, float]] = {}  # ip -> (count, first_fail_epoch)
_FAILED_LOCK = threading.Lock()


# ── helpers ──────────────────────────────────────────────────────────────────

def _token() -> str:
    return (os.getenv("APEX_AUTH_TOKEN") or "").strip()


def _enforced(app: Flask) -> bool:
    """Enforce always in production; stand down under pytest/app.testing
    unless APEX_AUTH_ENFORCE=true (set by the auth tests themselves)."""
    if os.getenv("APEX_AUTH_ENFORCE", "").strip().lower() == "true":
        return True
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    if getattr(app, "testing", False):
        return False
    return True


def _exempt(path: str) -> bool:
    if path in EXEMPT_EXACT:
        return True
    return any(path.startswith(p) for p in EXEMPT_PREFIXES)


def _header_token() -> str:
    key = (request.headers.get("X-APEX-KEY") or "").strip()
    if key:
        return key
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _matches(candidate: str, token: str) -> bool:
    if not candidate or not token:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), token.encode("utf-8"))


def _client_ip() -> str:
    fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return fwd or (request.remote_addr or "unknown")


def _lockout_remaining(ip: str) -> int:
    with _FAILED_LOCK:
        rec = _FAILED.get(ip)
        if not rec:
            return 0
        count, first = rec
        if count < MAX_FAILED_ATTEMPTS:
            return 0
        elapsed = time.time() - first
        if elapsed >= LOCKOUT_SECONDS:
            _FAILED.pop(ip, None)
            return 0
        return int(LOCKOUT_SECONDS - elapsed)


def _record_failure(ip: str) -> None:
    with _FAILED_LOCK:
        count, first = _FAILED.get(ip, (0, time.time()))
        # restart the window if the old one aged out
        if time.time() - first >= LOCKOUT_SECONDS:
            count, first = 0, time.time()
        _FAILED[ip] = (count + 1, first)


def _clear_failures(ip: str) -> None:
    with _FAILED_LOCK:
        _FAILED.pop(ip, None)


def _wants_html() -> bool:
    accept = (request.headers.get("Accept") or "").lower()
    return request.method == "GET" and "text/html" in accept


def _safe_next(raw: Optional[str]) -> str:
    """Only allow same-site relative paths as post-login redirect targets."""
    nxt = (raw or "").strip()
    if nxt.startswith("/") and not nxt.startswith("//") and ":" not in nxt:
        return nxt
    return "/apex_os"


_LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>APEX — Sign in</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#0b0f14;color:#d7e1ea;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
  .card{background:#111826;border:1px solid #1e2a3a;border-radius:12px;padding:32px 28px;
        width:min(360px,92vw);box-shadow:0 8px 40px rgba(0,0,0,.5)}
  h1{font-size:17px;letter-spacing:.12em;margin:0 0 4px;color:#7fd4a8}
  p{margin:0 0 20px;color:#7b8a99;font-size:13px}
  input{width:100%;box-sizing:border-box;background:#0b111c;border:1px solid #24344a;
        border-radius:8px;color:#d7e1ea;padding:11px 12px;font-size:15px;margin-bottom:14px}
  input:focus{outline:none;border-color:#3d6ea5}
  button{width:100%;background:#1d4ed8;border:0;border-radius:8px;color:#fff;
         padding:11px;font-size:14px;font-weight:600;cursor:pointer;letter-spacing:.05em}
  button:hover{background:#2563eb}
  .err{background:#2a1420;border:1px solid #5b2130;color:#f0a3b4;border-radius:8px;
       padding:9px 12px;font-size:13px;margin-bottom:14px}
</style></head><body>
<div class="card">
  <h1>APEX ACCESS</h1>
  <p>Enter the access token to continue.</p>
  {error}
  <form method="post" action="/login{qs}">
    <input type="password" name="token" placeholder="Access token" autofocus autocomplete="current-password">
    <button type="submit">Sign in</button>
  </form>
</div></body></html>"""


def _render_login(error: str = "", next_path: str = "") -> str:
    err_html = f'<div class="err">{error}</div>' if error else ""
    qs = f"?next={next_path}" if next_path else ""
    return _LOGIN_PAGE.replace("{error}", err_html).replace("{qs}", qs)


# ── install ──────────────────────────────────────────────────────────────────

def install_auth(app: Flask) -> None:
    """Attach the access-control gate and the /login /logout routes."""
    token = _token()

    # Cookie signing key: explicit FLASK_SECRET_KEY wins; otherwise derive
    # deterministically from the auth token so no second secret is needed.
    if not app.secret_key:
        explicit = (os.getenv("FLASK_SECRET_KEY") or "").strip()
        if explicit:
            app.secret_key = explicit
        elif token:
            app.secret_key = hashlib.sha256(
                ("apex-cookie-v1::" + token).encode("utf-8")
            ).hexdigest()
        else:
            # Placeholder so session machinery exists; gate 503s anyway.
            app.secret_key = hashlib.sha256(os.urandom(32)).hexdigest()

    try:
        hours = float(os.getenv("APEX_SESSION_HOURS", "12"))
    except ValueError:
        hours = 12.0
    app.permanent_session_lifetime = timedelta(hours=hours)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    cookie_secure = os.getenv("APEX_COOKIE_SECURE", "true").strip().lower() == "true"
    app.config["SESSION_COOKIE_SECURE"] = cookie_secure

    if token and len(token) < 16:
        print("AUTH WARNING: APEX_AUTH_TOKEN is under 16 characters — use a longer random token.", flush=True)
    if not token:
        print("AUTH: APEX_AUTH_TOKEN not set — all non-exempt routes will return 503 (fail closed).", flush=True)

    @app.route("/login", methods=["GET", "POST"])
    def _apex_login():  # pragma: no cover - exercised via tests below
        next_path = _safe_next(request.args.get("next"))
        if request.method == "GET":
            if session.get("apex_authed"):
                return redirect(next_path)
            return _render_login(next_path=request.args.get("next") or "")

        tok = _token()
        if not tok:
            return _render_login(error="Server has no APEX_AUTH_TOKEN configured."), 503

        ip = _client_ip()
        remaining = _lockout_remaining(ip)
        if remaining > 0:
            return _render_login(
                error=f"Too many failed attempts. Locked for {remaining // 60 + 1} more minute(s)."
            ), 429

        supplied = (request.form.get("token") or "").strip()
        if _matches(supplied, tok):
            _clear_failures(ip)
            session.permanent = True
            session["apex_authed"] = True
            session["apex_authed_at"] = time.time()
            return redirect(next_path)

        _record_failure(ip)
        return _render_login(error="Invalid token.", next_path=request.args.get("next") or ""), 401

    @app.route("/logout", methods=["GET", "POST"])
    def _apex_logout():
        session.clear()
        return redirect("/login")

    @app.before_request
    def _apex_access_gate():
        try:
            path = request.path or "/"
            if _exempt(path):
                return None
            if not _enforced(app):
                return None

            tok = _token()
            if not tok:
                return jsonify({
                    "ok": False,
                    "error": "auth not configured",
                    "detail": "Set APEX_AUTH_TOKEN in the environment. All non-exempt routes are disabled until then (fail closed).",
                }), 503

            if _matches(_header_token(), tok):
                return None
            if session.get("apex_authed"):
                return None

            if _wants_html():
                return redirect(f"/login?next={path}")
            return jsonify({
                "ok": False,
                "error": "unauthorized",
                "detail": "Provide X-APEX-KEY: <token> (or Authorization: Bearer <token>), or sign in at /login.",
            }), 401
        except Exception as gate_err:  # never fail open
            print(f"AUTH GATE ERROR (denying request): {gate_err}", flush=True)
            return jsonify({"ok": False, "error": "auth gate error"}), 401


def auth_status() -> Dict[str, Any]:
    """Small introspection payload for diagnostics dashboards."""
    tok = _token()
    return {
        "version": VERSION,
        "configured": bool(tok),
        "token_length": len(tok),
        "exempt_exact": sorted(EXEMPT_EXACT),
        "exempt_prefixes": list(EXEMPT_PREFIXES),
        "lockout_policy": {
            "max_failed_attempts": MAX_FAILED_ATTEMPTS,
            "lockout_seconds": LOCKOUT_SECONDS,
        },
    }
