"""Read-only one-shot sampling sanity tests (does not assume a Linux cgroup in CI)."""
from pathlib import Path
import importlib.util

SCRIPT = Path(__file__).with_name('cross_process_snapshot.py')
# Script is packaged separately and checked without importing it into scanner.

def test_script_has_no_mutating_interfaces():
    text = SCRIPT.read_text()
    for token in ('sqlite3.connect', 'os.kill(', 'gc.collect(', 'drop_caches', 'wal_checkpoint(', 'VACUUM'):
        assert token not in text
    assert 'process_start_ticks' in text
    assert 'process_visibility_truncated' in text
