"""Phase 3B isolated subprocess crash/restart checks."""
import subprocess
import sys
import unittest

from scripts.apex_forward_phase3b_staging import run_phase3b


class Phase3BIntegrationTests(unittest.TestCase):
    def test_rehearsal(self):
        report = run_phase3b()
        self.assertTrue(report['ok'])
        self.assertEqual(report['authentication'], 'NOT_REAL_WORLD_AUTHENTICATION')
        self.assertEqual(report['promotion_authority'], 'NONE')
        self.assertFalse(report['production_data_accessed'])
        self.assertGreaterEqual(report['total_passed'], 10)

    def test_cli_exit_and_report(self):
        proc = subprocess.run([sys.executable, '-m', 'scripts.apex_forward_phase3b_staging', '--json'],
                              capture_output=True, text=True, timeout=45)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn('"phase": "3B"', proc.stdout)
        self.assertIn('"ok": true', proc.stdout)


if __name__ == '__main__':
    unittest.main()
