import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b38_historical_render_runtime_audit.py'
spec=importlib.util.spec_from_file_location('b38',SCRIPT)
b38=importlib.util.module_from_spec(spec);spec.loader.exec_module(b38)
SERVICE='srv-d7p3u2navr4c73d2q0jg'
CANDIDATE=b38.B37.DEFAULT_CANDIDATE


def deployment(ident,sha,when,status='deactivated'):
    return {'id':ident,'commit':{'id':sha},'startedAt':when,'finishedAt':when,'status':status}


def event(ident,when,status='succeeded'):
    return {'id':'evt-'+ident[4:],'serviceId':SERVICE,'type':'deploy_ended','timestamp':when,
            'details':{'deployId':ident,'deployStatus':status}}


class TestStage38(unittest.TestCase):
    def test_flat_raw_list(self):
        out,n=b38.flatten_pages([{'id':'dep-123'}],'deploys')
        self.assertEqual((len(out),n),(1,1))

    def test_pages_container(self):
        doc={'pages':[[{'id':'dep-123'}],{'results':[{'id':'dep-456'}]}]}
        out,n=b38.flatten_pages(doc,'deploys')
        self.assertEqual((len(out),n),(2,2))

    def test_caps_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'PAGE_COUNT_LIMIT'):
            b38.flatten_pages({'pages':[[]]*65},'events')

    def test_api_cursor_pagination(self):
        calls=[]
        def fetch(url,key):
            calls.append(url)
            if len(calls)==1:return [{'cursor':'c1'}]*100
            return [{'id':'x'}]
        rows,state=b38.acquire_pages(SERVICE,'dummy','deploys',300,5,fetch)
        self.assertEqual(len(rows),101)
        self.assertTrue(state['pagination_exhausted'])
        self.assertIn('cursor=c1',calls[1])

    def test_api_full_page_missing_cursor_not_exhausted(self):
        rows,state=b38.acquire_pages(SERVICE,'dummy','events',300,5,lambda *_:[{}]*100)
        self.assertFalse(state['pagination_exhausted'])
        self.assertEqual(state['stop_reason'],'FULL_PAGE_WITHOUT_CURSOR')

    def test_window_filter(self):
        start=b38.utc('2026-09-01T00:00:00Z');end=b38.utc('2026-10-15T00:00:00Z')
        sha='a'*40
        ds=[deployment('dep-aaa',sha,'2026-09-18T15:00:00Z'),deployment('dep-bbb',sha,'2026-11-18T15:00:00Z')]
        es=[event('dep-aaa','2026-09-18T15:00:00Z'),event('dep-bbb','2026-11-18T15:00:00Z')]
        a,b,_=b38.normalize_window(ds,es,SERVICE,start,end)
        self.assertEqual((len(a),len(b)),(1,1))

    def test_runtime_untrusted(self):
        d={'deploy_id':'dep-aaa','sha':'a'*40,'started_at':b38.utc('2026-09-18T14:00:00Z'),
           'completed_at':b38.utc('2026-09-18T14:05:00Z')}
        claim={'deploy_id':'dep-aaa','commit_sha':'a'*40,'observed_at':'2026-09-18T15:00:00Z',
               'canonical_gamma_snapshot_id':'gamma-123'}
        r=b38.runtime_observations([claim],SERVICE,[d])
        self.assertEqual(r['claims_with_gamma_identity'],1)
        self.assertFalse(r['runtime_activation_verified'])

    def test_runtime_mismatched_sha(self):
        d={'deploy_id':'dep-aaa','sha':'a'*40,'started_at':b38.utc('2026-09-18T14:00:00Z'),
           'completed_at':b38.utc('2026-09-18T14:05:00Z')}
        r=b38.runtime_observations([{'deploy_id':'dep-aaa','commit_sha':'b'*40,
          'observed_at':'2026-09-18T15:00:00Z','canonical_gamma_snapshot_id':'x'}],SERVICE,[d])
        self.assertEqual(r['linked_claims'],0)

    def test_invalid_service_record_rejected(self):
        d=deployment('dep-aaa','a'*40,'2026-09-18T15:00:00Z')
        self.assertIsNone(b38.B332.normalize_deploy({'id':'incorrect'},SERVICE))
        self.assertIsNotNone(b38.B332.normalize_deploy(d,SERVICE))

    def test_actual_git_before_after_bracket_remains_unattested(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)/'repo';repo.mkdir()
            def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
            git('init','-q');git('config','user.name','Test');git('config','user.email','test@example.invalid')
            for path in b38.B37.CONTRACT:
                f=repo/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('baseline=1\n')
            git('add','.');git('commit','-qm','parent');parent=git('rev-parse','HEAD')
            for path,contract in b38.B37.CONTRACT.items():
                funcs='\n'.join('def '+f+'(): pass' for f in contract['functions'])
                markers='\n'.join('# '+m for m in contract['tokens'])
                (repo/path).write_text(funcs+'\n'+markers+'\n')
            git('add','.');git('commit','-qm','candidate');candidate=git('rev-parse','HEAD')
            ds=[deployment('dep-aaa',parent,'2026-09-18T10:00:00Z'),
                deployment('dep-bbb',candidate,'2026-09-18T12:00:00Z')]
            es=[event('dep-aaa','2026-09-18T10:00:00Z'),event('dep-bbb','2026-09-18T12:00:00Z')]
            r,d=b38.run(repo=repo,service=SERVICE,candidate=candidate,deploy_raw=ds,event_raw=es,
                       start=b38.utc('2026-09-01T00:00:00Z'),end=b38.utc('2026-10-15T00:00:00Z'))
            self.assertTrue(r['observations']['offline_before_after_bracket_candidate'])
            self.assertEqual(r['observations']['candidate_relation_counts']['before'],1)
            self.assertEqual(r['observations']['candidate_relation_counts']['after'],1)
            self.assertFalse(r['observations']['runtime_gamma_activation_verified'])
            self.assertEqual(r['migration_authority'],'BLOCKED_RESEARCH_ONLY')

    def test_end_to_end_no_git_never_claims_activation(self):
        sha='a'*40
        ds=[deployment('dep-aaa',sha,'2026-09-18T15:00:00Z')]
        es=[event('dep-aaa','2026-09-18T15:00:00Z')]
        with tempfile.TemporaryDirectory() as td:
            report,details=b38.run(repo=td,service=SERVICE,candidate=CANDIDATE,
              deploy_raw=ds,event_raw=es,start=b38.utc('2026-09-01T00:00:00Z'),
              end=b38.utc('2026-10-15T00:00:00Z'),evidence_out_dir=Path(td)/'evidence')
            self.assertEqual(report['migration_authority'],'BLOCKED_RESEARCH_ONLY')
            self.assertFalse(report['observations']['runtime_gamma_activation_verified'])
            self.assertEqual(report['observations']['selected_window_successful_event_claims'],1)
            self.assertTrue((Path(td)/'evidence'/'stage3b38-deployment-history.json').exists())

if __name__=='__main__':unittest.main()
