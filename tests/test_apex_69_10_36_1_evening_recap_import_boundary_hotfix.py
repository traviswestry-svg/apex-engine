"""APEX 69.10.36.1 — Evening Recap import-boundary hotfix regression tests."""
from pathlib import Path
from types import SimpleNamespace

import engine.evening_recap_service as svc

ROOT = Path(__file__).resolve().parents[1]


def test_flask_routes_do_not_directly_import_evening_recap_implementation():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from engine.evening_recap import save_morning_snapshot" not in src
    assert "from engine.evening_recap import morning_history" not in src
    assert "from engine.evening_recap_service import save_morning_snapshot" in src
    assert "from engine.evening_recap_service import morning_history" in src
    assert "from engine.evening_recap_service import generate_evening_recap, get_morning_snapshot" in src


def test_service_boundary_exposes_morning_archive_operations(monkeypatch):
    calls = []
    fake = SimpleNamespace(
        save_morning_snapshot=lambda payload, ticker="SPX": calls.append(("save", payload, ticker)) or {"archived": True},
        morning_history=lambda limit=60: calls.append(("history", limit)) or {"items": []},
    )
    monkeypatch.setattr(svc, "_impl", lambda: fake)
    payload = {"session_date": "2026-10-07"}
    assert svc.save_morning_snapshot(payload, ticker="SPX") == {"archived": True}
    assert svc.morning_history("12") == {"items": []}
    assert calls == [("save", payload, "SPX"), ("history", "12")]


def test_evening_recap_route_logs_full_exception_traceback():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'app.logger.exception("[APEX49] evening recap failed")' in src
