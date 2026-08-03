import time
from unittest.mock import Mock

from engine.execution.broker_interface import BrokerResult, OrderIntent
from engine.execution.canonical_execution import CanonicalExecutionBoundary
from engine.learning_maturity import maturity_contract


def _contract(**overrides):
    c = {
        "symbol": "SPX", "side": "CALL", "expiration": "2099-01-01",
        "bid": 9.9, "ask": 10.1, "spread_pct": 2.0, "quote_age_seconds": 1.0,
        "osi_key": "SPXW TEST",
    }
    c.update(overrides)
    return c


def _intent():
    return OrderIntent(symbol="SPX", osi_key="SPXW TEST", side="CALL",
                       action="BUY_OPEN", quantity=1, limit_price=10.0, tag="ENTRY")


def test_learning_maturity_blocks_thin_sample_confidence():
    early = maturity_contract(1, 5, source="EARLY_ZONE_HISTORY")
    assert early["maturity"] == "EARLY_SAMPLE"
    assert early["statistically_usable"] is False
    assert early["display_policy"] == "DO_NOT_RENDER_AS_CALIBRATED_CONFIDENCE"
    ready = maturity_contract(5, 5, source="HISTORICAL_ZONE")
    assert ready["statistically_usable"] is True


def test_canonical_boundary_revalidates_risk_at_placement(monkeypatch):
    boundary = CanonicalExecutionBoundary()
    adapter = Mock(mode="sandbox", trading_enabled=False)
    adapter.place_order.return_value = BrokerResult(ok=True, mode="sandbox", data={"order_id": "1"})
    boundary.register_preview("p1", contract=_contract(), quantity=1, entry_premium=10.0,
                              stop_premium=8.0, session_state="MARKET_OPEN", intent=_intent())
    # Changed placement state is unsafe: stale quote. Must fail before adapter I/O.
    result = boundary.execute_single_leg(adapter=adapter, preview_id="p1", intent=_intent(),
        contract=_contract(quote_age_seconds=999), quantity=1, entry_premium=10.0,
        stop_premium=8.0, session_state="MARKET_OPEN", last_order_epoch=None)
    assert result.ok is False
    adapter.place_order.assert_not_called()


def test_canonical_boundary_blocks_duplicate_submit(monkeypatch):
    import engine.execution.canonical_execution as ce
    monkeypatch.setattr(ce.guard, "validate_entry", lambda **kwargs: Mock(allow=True, reasons=[], warnings=[], to_dict=lambda: {"allow": True}))
    boundary = CanonicalExecutionBoundary()
    adapter = Mock(mode="sandbox", trading_enabled=False)
    adapter.place_order.return_value = BrokerResult(ok=True, mode="sandbox", data={"order_id": "1"})
    boundary.register_preview("p2", contract=_contract(), quantity=1, entry_premium=10.0,
                              stop_premium=8.0, session_state="MARKET_OPEN", intent=_intent())
    kwargs=dict(adapter=adapter, preview_id="p2", intent=_intent(), contract=_contract(), quantity=1,
                entry_premium=10.0, stop_premium=8.0, session_state="MARKET_OPEN", last_order_epoch=None)
    assert boundary.execute_single_leg(**kwargs).ok is True
    assert boundary.execute_single_leg(**kwargs).ok is False
    assert adapter.place_order.call_count == 1


def test_hlce_route_registration_has_no_collector_start_side_effect():
    from pathlib import Path
    src = Path("engine/historical_level_calibration_routes.py").read_text()
    assert "service.start(" not in src
    scanner = Path("scanner_worker.py").read_text()
    assert "service.start(_hlce_snapshot_provider)" in scanner


def test_runtime_db_files_are_ignored():
    from pathlib import Path
    ignore = Path(".gitignore").read_text()
    assert "*.db" in ignore


def test_hlce_accepts_durable_canonical_level_list(tmp_path):
    from engine.historical_level_calibration import Collector, initialize_store
    db = str(tmp_path / "calibration.db")
    initialize_store(db)
    collector = Collector(db)
    snapshot = {
        "ticker": "SPX",
        "spot": 7543.76,
        "market_state": {"price": 7543.76},
        "canonical_levels": [
            {"kind": "prev_day_high", "price": 7512.04, "source": "polygon"},
            {"kind": "expected_move_high", "price": 7567.01, "source": "computed"},
            {"kind": "call_wall", "price": 7550.0, "source": "gamma_provider"},
        ],
    }
    out = collector.observe(snapshot, now=1785765600.0)
    assert out["ok"] is True
    import sqlite3
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM daily_levels").fetchone()[0] == 3
        assert c.execute("SELECT COUNT(*) FROM level_price_samples").fetchone()[0] == 1


def test_scanner_hlce_provider_no_longer_uses_raw_last_result_lambda():
    from pathlib import Path
    scanner = Path("scanner_worker.py").read_text()
    assert "service.start(_hlce_snapshot_provider)" in scanner
    assert 'start(lambda: dict(apex_app.STATE.get("last_result") or {}))' not in scanner
    assert "latest_canonical_context" in scanner
    assert "ticker.any_of=I:SPX" in scanner


def test_6572_render_supervises_scanner_process():
    from pathlib import Path
    src = Path("start_render.sh").read_text()
    assert "SCANNER_PID=$!" in src
    assert "WEB_PID=$!" in src
    assert 'kill -0 "$SCANNER_PID"' in src
    assert "scanner process exited" in src


def test_6572_scanner_has_live_bar_fallback_and_self_heal():
    from pathlib import Path
    src = Path("scanner_worker.py").read_text()
    assert "get_intraday_bars" in src
    assert "def _ensure_hlce_running" in src
    assert "service.collector_running()" in src
    assert "hlce_provider_ok" in src
    assert "hlce_counts" in src


def test_6572_status_reports_scanner_owned_collector():
    from pathlib import Path
    src = Path("engine/historical_level_calibration_routes.py").read_text()
    assert 'payload["collector_owner"] = "scanner_process"' in src
    assert 'payload["local_web_collector_running"]' in src
    assert 'payload["collector_status_source"]' in src
    assert "read_scanner_heartbeat" in src
    assert "supervisor_status" in src


def test_6573_wsgi_has_direct_gunicorn_scanner_fallback():
    from pathlib import Path
    src = Path("wsgi.py").read_text()
    assert "ensure_scanner_process" in src
    assert 'app.config["APEX_SCANNER_SUPERVISOR"]' in src
    supervisor = Path("engine/scanner_process_supervisor.py").read_text()
    assert 'cmd = [sys.executable, "scanner_worker.py"]' in supervisor
    assert "APEX_SCANNER_MANAGED_EXTERNALLY" in supervisor
    assert "_watchdog_loop" in supervisor


def test_6573_shell_launcher_disables_wsgi_duplicate_launcher():
    from pathlib import Path
    src = Path("start_render.sh").read_text()
    assert "export APEX_SCANNER_MANAGED_EXTERNALLY=true" in src
    assert "python scanner_worker.py &" in src


def test_6573_scanner_takes_process_lease_before_app_import_and_bootstraps_heartbeat():
    from pathlib import Path
    src = Path("scanner_worker.py").read_text()
    lease_pos = src.index("_PROCESS_LEASE = acquire_scanner_lease()")
    app_pos = src.index("import app as apex_app")
    assert lease_pos < app_pos
    assert '"phase": "IMPORTING_APP"' in src
    assert '"phase": "APP_IMPORT_FAILED"' in src
    assert '"phase": "RUNNING"' in src
    assert '"bootstrap_source"' in src


def test_6573_supervisor_respects_external_management(monkeypatch):
    import engine.scanner_process_supervisor as sps
    monkeypatch.setenv("APEX_SCANNER_MANAGED_EXTERNALLY", "true")
    monkeypatch.setenv("APEX_WSGI_ENSURE_SCANNER", "true")
    called = {"launch": 0}
    monkeypatch.setattr(sps, "_launch_locked", lambda: called.__setitem__("launch", called["launch"] + 1))
    out = sps.ensure_scanner_process()
    assert out["managed_externally"] is True
    assert called["launch"] == 0


def test_6574_wsgi_has_serving_worker_request_bootstrap():
    from pathlib import Path
    src = Path("wsgi.py").read_text()
    assert "@app.before_request" in src
    assert "_apex_6574_scanner_lifecycle_guard" in src
    assert "_ensure_scanner_after_worker_init()" in src


def test_6574_missing_heartbeat_launches_even_if_supervisor_lease_unavailable(monkeypatch):
    import engine.scanner_process_supervisor as sps
    monkeypatch.delenv("APEX_SCANNER_MANAGED_EXTERNALLY", raising=False)
    monkeypatch.setenv("APEX_WSGI_ENSURE_SCANNER", "true")
    monkeypatch.delenv("DISABLE_BACKGROUND_SCANNER", raising=False)
    called = {"launch": 0}
    monkeypatch.setattr(sps, "_heartbeat_fresh", lambda *a, **k: False)
    monkeypatch.setattr(sps, "_acquire_supervisor_lease", lambda: False)
    monkeypatch.setattr(sps, "_launch_locked", lambda: called.__setitem__("launch", called["launch"] + 1))
    out = sps.ensure_scanner_process()
    assert called["launch"] == 1
    assert out["owner"] is False
    assert out["ensure_calls"] >= 1


def test_6574_supervisor_exposes_bootstrap_diagnostics():
    from pathlib import Path
    src = Path("engine/scanner_process_supervisor.py").read_text()
    assert 'VERSION = "65.7.5_APP_ENTRYPOINT_BOOTSTRAP"' in src
    assert '"ensure_calls": 0' in src
    assert '"lease_acquired": False' in src
    assert '"lease_error": None' in src


def test_6575_app_module_is_unavoidable_scanner_bootstrap_boundary():
    from pathlib import Path
    src = Path("app.py").read_text()
    assert '_apex6575_ensure_scanner_process(source="app_module_import")' in src
    assert 'app.config["APEX_SCANNER_SUPERVISOR"]' in src
    # The bootstrap is registered before direct-execution handling, so app:app,
    # wsgi:app, factories, and python app.py all cross the same boundary.
    assert src.index('_apex6575_ensure_scanner_process(source="app_module_import")') < src.index('if __name__ == "__main__":')


def test_6575_scanner_marks_process_before_importing_app():
    from pathlib import Path
    src = Path("scanner_worker.py").read_text()
    marker = src.index('os.environ["APEX_SCANNER_PROCESS"] = "true"')
    app_import = src.index("import app as apex_app")
    assert marker < app_import


def test_6575_supervisor_skips_recursive_scanner_child(monkeypatch):
    import engine.scanner_process_supervisor as sps
    monkeypatch.setenv("APEX_SCANNER_PROCESS", "true")
    called = {"launch": 0}
    monkeypatch.setattr(sps, "_launch_locked", lambda: called.__setitem__("launch", called["launch"] + 1))
    out = sps.ensure_scanner_process(source="scanner_child_test")
    assert called["launch"] == 0
    assert out["skipped_scanner_child"] is True
    assert out["last_ensure_source"] == "scanner_child_test"


def test_6575_supervisor_child_env_marks_scanner(monkeypatch):
    from pathlib import Path
    src = Path("engine/scanner_process_supervisor.py").read_text()
    assert 'env["APEX_SCANNER_PROCESS"] = "true"' in src
    assert 'VERSION = "65.7.5_APP_ENTRYPOINT_BOOTSTRAP"' in src
    assert '"last_ensure_source": None' in src
