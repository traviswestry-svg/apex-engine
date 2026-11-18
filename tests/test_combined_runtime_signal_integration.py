"""Combined APEX candidate integration regression checks."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text()

def test_signal_integrity_guard_remains_wired():
    assert "from engine.signal_integrity_guard import evaluate_signal_thresholds, finite_number" in APP
    assert "reason, level, missing = evaluate_signal_thresholds(" in APP
    assert "threshold_resolution=ABSTAIN" in APP

def test_volume_profile_timing_remains_wired():
    assert "volume_profile duration_ms=" in APP
    assert "volume_bundle, vp_status, vp_elapsed_ms = _ios_vp_fetch(" in APP

def test_full_scan_diagnostics_are_present():
    tree = ast.parse(APP)
    fn = next(n for n in tree.body if isinstance(n, (ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == "run_scan_once")
    code = ast.get_source_segment(APP,fn)
    for event in ('"ATTEMPT"','"COMPLETED"','"FAILED"','"SKIPPED"','"FULL_SCAN"'):
        assert event in code
    assert 'SCAN_LOCK.acquire(blocking=False)' in code

def test_scheduler_diagnostics_are_present():
    assert '"SCHEDULER_ITERATION"' in APP
    assert 'scan_event(new_cycle_id("scheduler")' in APP

def test_authority_not_changed():
    diag = (ROOT / 'engine/paired_runtime_diagnostics.py').read_text()
    assert '"decision_authority":False' in diag
    assert '"execution_authority":False' in diag
