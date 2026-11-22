import json
import subprocess
import sys
import unittest
from engine.forward_provenance_external_authority import create_staging_bundle
from scripts.apex_forward_phase3c_staging import rehearse

class Phase3CTests(unittest.TestCase):
    def test_authority_refuses_production_context(self):
        with self.assertRaisesRegex(ValueError, 'production signing is not supported'):
            create_staging_bundle(audit_copy='unused', observed_facts={'environment': 'PRODUCTION'},
                                  operator_private_key=None, observed_at='')

    def test_isolated_off_host_rehearsal(self):
        result=rehearse()
        self.assertTrue(result['ok'])
        self.assertEqual(result['total_passed'],15)
        self.assertEqual(result['promotion_authority'],'NONE')
        self.assertFalse(result['production_data_accessed'])
    def test_command_line(self):
        p=subprocess.run([sys.executable,'-m','scripts.apex_forward_phase3c_staging','--json'],
                         capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr+' '+p.stdout)
        obj=json.loads(p.stdout)
        self.assertTrue(obj['ok'])
        self.assertEqual(obj['total_passed'],15)

if __name__=='__main__': unittest.main()
