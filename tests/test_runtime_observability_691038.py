from engine.scanner_runtime_truth import resolve_scanner_runtime
from engine.runtime_memory_pressure import classify_memory


def test_fresh_scanner_is_authoritative_even_after_hours():
    hb = {"available": True, "age_seconds": 2, "scanner_started": True,
          "thread_alive": True, "pid": 41, "phase": "RUNNING", "updated_at": "2026-10-14T22:02:41+00:00"}
    x = resolve_scanner_runtime(local_started=False, local_thread_alive=False, heartbeat=hb)
    assert x["authority"] == "SCANNER_PROCESS"
    assert x["effective_thread_alive"] is True
    assert x["process_pid"] == 41
    assert x["heartbeat_reason"] == "FRESH"


def test_stale_scanner_explains_fallback():
    x = resolve_scanner_runtime(local_started=False, local_thread_alive=False,
                                heartbeat={"available": True, "age_seconds": 46})
    assert x["authority"] == "WEB_PROCESS_FALLBACK"
    assert x["heartbeat_reason"] == "HEARTBEAT_STALE"


def test_missing_reader_error_preserved():
    x = resolve_scanner_runtime(local_started=False, local_thread_alive=False,
                                heartbeat={"available": False, "error": "FileNotFoundError"})
    assert x["heartbeat_error"] == "FileNotFoundError"
    assert x["heartbeat_reason"] == "HEARTBEAT_UNAVAILABLE"


def test_reclaimable_file_cache_not_called_critical_pressure():
    x = classify_memory(current=3962519552, limit=4294967296,
                        inactive_file=2123251712, events={"oom": 0, "oom_kill": 0},
                        psi_some_avg10=0, psi_full_avg10=0)
    assert x["raw_usage_pct"] > 90
    assert x["estimated_noninactive_file_usage_pct"] < 50
    assert x["severity"] == "HIGH_RAW_USAGE_NO_CONFIRMED_PRESSURE"


def test_psi_pressure_elevates_classification():
    x = classify_memory(current=300, limit=1000, psi_full_avg10=1.5)
    assert x["severity"] == "CRITICAL"


def test_unlimited_cgroup_is_unknown():
    assert classify_memory(current=300, limit=None)["severity"] == "UNKNOWN"
