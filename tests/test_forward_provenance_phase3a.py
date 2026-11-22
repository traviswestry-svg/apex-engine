"""Phase 3A integration guardrails: disposable synthetic environment only."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.apex_forward_phase3a_staging import run_phase3a

ROOT = Path(__file__).resolve().parents[1]


class Phase3AIntegrationTests(unittest.TestCase):
    def test_rehearsal_passes_and_is_explicitly_non_authoritative(self):
        result = run_phase3a()
        self.assertTrue(result['ok'])
        self.assertEqual(result['environment'], 'DISPOSABLE_SYNTHETIC_ONLY')
        self.assertEqual(result['authentication'], 'NOT_REAL_WORLD_AUTHENTICATION')
        self.assertEqual(result['promotion_authority'], 'NONE')
        self.assertFalse(result['production_data_accessed'])
        self.assertGreaterEqual(result['total_passed'], 10)
        self.assertTrue(all(v == 'PASS' for v in result['cases'].values()))

    def test_command_line_entrypoint(self):
        env = dict(os.environ)
        env['PYTHONPATH'] = str(ROOT)
        process = subprocess.run([sys.executable, '-m',
              'scripts.apex_forward_phase3a_staging', '--json'],
              cwd=ROOT, env=env, text=True, capture_output=True, timeout=25)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn('"NOT_REAL_WORLD_AUTHENTICATION"', process.stdout)


if __name__ == '__main__':
    unittest.main()
