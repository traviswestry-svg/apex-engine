"""Web worker containment does not modify scanner or execution authority."""
from pathlib import Path
import re
import subprocess


def test_start_script_syntax():
    subprocess.run(["bash", "-n", "start_render.sh"], check=True)


def test_gunicorn_recycles_bounded_web_workers_only():
    src = Path("start_render.sh").read_text()
    assert "--workers 1" in src and "--threads 4" in src
    assert "--max-requests 80" in src
    assert "--max-requests-jitter 20" in src
    assert "--graceful-timeout 120" in src
    assert src.index("python scanner_worker.py &") < src.index("gunicorn wsgi:app")
    assert "APEX_SCANNER_MANAGED_EXTERNALLY=true" in src
    assert 'if ! kill -0 "$SCANNER_PID"' in src


def test_no_unsafe_memory_actions():
    src = Path("start_render.sh").read_text()
    assert "drop_caches" not in src
    assert "kill -9" not in src
    assert "memory.current" not in src
    assert "memory.max" not in src
    assert "TRADERSPOST" not in src
    assert "sqlite3" not in src
    assert re.search(r"gunicorn wsgi:app.*--bind", src)
