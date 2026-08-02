import subprocess
import sys
import textwrap


def _run(code: str):
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_ltpe_import_does_not_eagerly_import_hlce():
    proc = _run("""
        import importlib, sys
        ltpe = importlib.import_module('engine.level_transition_probability')
        assert callable(ltpe.learning_status)
        assert callable(ltpe.run_learning_cycle)
        assert 'engine.historical_level_calibration' not in sys.modules
    """)
    assert proc.returncode == 0, proc.stderr


def test_hlce_and_ltpe_can_resolve_concurrently_without_partial_module_error():
    proc = _run("""
        import importlib, threading
        errors=[]
        barrier=threading.Barrier(2)
        def a():
            try:
                barrier.wait(2)
                mod=importlib.import_module('engine.level_transition_probability')
                assert callable(mod.learning_status)
            except Exception as exc:
                errors.append(repr(exc))
        def b():
            try:
                barrier.wait(2)
                importlib.import_module('engine.historical_level_calibration')
                mod=importlib.import_module('engine.level_transition_probability')
                assert callable(mod.run_learning_cycle)
            except Exception as exc:
                errors.append(repr(exc))
        t1=threading.Thread(target=a); t2=threading.Thread(target=b)
        t1.start(); t2.start(); t1.join(5); t2.join(5)
        assert not t1.is_alive() and not t2.is_alive()
        assert errors == [], errors
    """)
    assert proc.returncode == 0, proc.stderr


def test_lazy_proxy_resolves_hlce_only_after_ltpe_is_complete():
    proc = _run("""
        import importlib, sys
        ltpe=importlib.import_module('engine.level_transition_probability')
        assert 'engine.historical_level_calibration' not in sys.modules
        assert callable(ltpe.hlce._connect)
        assert 'engine.historical_level_calibration' in sys.modules
        assert callable(ltpe.learning_status)
    """)
    assert proc.returncode == 0, proc.stderr
