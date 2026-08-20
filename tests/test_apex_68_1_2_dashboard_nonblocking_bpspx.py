import ast
from pathlib import Path


def test_bpspx_provider_io_is_not_called_directly_from_dashboard_composition():
    source = Path("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    direct_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "refresh_bpspx_observation":
                direct_calls.append(node.lineno)
    # The only direct call belongs to the daemon worker; the dashboard
    # composition calls schedule_bpspx_refresh() and cannot wait on Polygon.
    assert len(direct_calls) == 1
    assert "schedule_bpspx_refresh()" in source


def test_bpspx_refresh_thread_is_daemonized_and_throttled():
    source = Path("app.py").read_text(encoding="utf-8")
    assert 'name="apex-bpspx-refresh", daemon=True' in source
    assert "_BPSPX_REFRESH_INTERVAL_SECONDS" in source
