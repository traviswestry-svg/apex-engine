"""No network and no production data in Phase 4A regression tests."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from engine.forward_provenance_render_observer import collect, ObservationError, canonical
from scripts.apex_forward_phase4a_observer import run

SVC = 'srv-example123'
SHA = 'a'*40

def deploy(id='dep-test001', status='live', sha=SHA):
    return {'deploy': {'id':id,'status':status,'commit':{'id':sha},
            'createdAt':'2026-11-20T10:00:00Z','finishedAt':'2026-11-20T10:01:00Z'},'cursor':'cursor1'}

class Phase4ATests(unittest.TestCase):
    def get(self, path, params):
        return {'id': SVC} if not path.endswith('/deploys') else ([deploy()] if 'cursor' not in params else [])

    def test_provider_observation_is_not_process_attestation(self):
        r=collect(SVC,self.get,observed_at='2026-11-22T00:00:00Z')
        self.assertTrue(r['ok']);self.assertEqual(r['verdict'],'NO_GO')
        self.assertIsNone(r['evidence']['process_pid'])
        self.assertFalse(r['evidence']['production_activation_authorized'])
        self.assertEqual(r['sha256_evidence'],hashlib.sha256(canonical(r['evidence'])).hexdigest())

    def test_invalid_service_rejected(self):
        with self.assertRaises(ObservationError):collect('https://evil.org',self.get)

    def test_mismatched_service_rejected(self):
        with self.assertRaises(ObservationError):collect(SVC,lambda p,q:{'id':'srv-other'} if not p.endswith('deploys') else [])

    def test_invalid_sha_rejected(self):
        def getter(path, params):
            return {'id': SVC} if not path.endswith('/deploys') else ([deploy(sha='not-a-sha')] if 'cursor' not in params else [])
        with self.assertRaises(ObservationError):collect(SVC,getter)

    def test_duplicate_deploy_fails_closed(self):
        def getter(path, params):
            return {'id': SVC} if not path.endswith('/deploys') else ([deploy(),deploy()] if 'cursor' not in params else [])
        with self.assertRaisesRegex(ObservationError,'DUPLICATE_DEPLOY'):collect(SVC,getter)

    def test_cursor_cycle_rejected(self):
        def getter(path, params):
            return {'id': SVC} if not path.endswith('/deploys') else [deploy()]*100
        with self.assertRaises(ObservationError):collect(SVC,getter,max_pages=3)

    def test_max_page_fail_closed(self):
        def getter(path, params):
            return {'id': SVC} if not path.endswith('/deploys') else [deploy(id='dep-test000')] + [
                deploy(id=f'dep-foo{i:03d}') for i in range(1,100)]
        with self.assertRaises(ObservationError):collect(SVC,getter,max_pages=1)

    def test_ambiguous_live_no_guess(self):
        def getter(path, params):
            return {'id': SVC} if not path.endswith('/deploys') else ([deploy('dep-test001'),deploy('dep-test002')] if 'cursor' not in params else [])
        r=collect(SVC,getter)
        self.assertEqual(r['evidence']['provider_deployment_observation'],'LIVE_DEPLOY_AMBIGUOUS')

    def test_fixture_cli_never_production_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            fixture=Path(d)/'fixture.json'; out=Path(d)/'output.json'
            fixture.write_text(json.dumps({'service':{'id':SVC},'pages':[[deploy()]]}))
            report,code=run(['--fixture',str(fixture),'--service-id',SVC,'--out',str(out)])
            self.assertEqual(code,0)
            self.assertEqual(report['capture_mode'],'OFFLINE_FIXTURE_NOT_OBSERVED')
            self.assertTrue(out.exists())
            report2,code2=run(['--fixture',str(fixture),'--service-id',SVC,'--out',str(out)])
            self.assertEqual(code2,2)
            self.assertEqual(report2['reason'],'OUTPUT_EXISTS_OR_SYMLINK')

    def test_no_token_fails_closed(self):
        from unittest.mock import patch
        with patch.dict('os.environ',{},clear=True):
            r,code=run(['--live-render-api','--service-id',SVC])
        self.assertEqual(code,2);self.assertEqual(r['reason'],'MISSING_API_CREDENTIAL')

if __name__ == '__main__':unittest.main()
