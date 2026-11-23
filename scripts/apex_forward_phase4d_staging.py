"""Disposable Phase 4D verification rehearsal. No production access or writes."""
import argparse
import json
import unittest

def run():
    from tests.test_forward_provenance_phase4d import Phase4DTests
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Phase4DTests)
    result=unittest.TestResult();suite.run(result)
    return {'phase':'4D','ok':result.wasSuccessful(),
            'checks_passed':result.testsRun-len(result.failures)-len(result.errors),
            'checks_total':result.testsRun,
            'failures':[str(t)+': '+e.splitlines()[-1] for t,e in result.failures+result.errors],
            'environment':'DISPOSABLE_SYNTHETIC_ONLY',
            'deployment_authentication':'STAGING_SIGNATURE_CONSISTENCY_ONLY',
            'external_storage':'NOT_DEPLOYED','independent_collector':'NOT_DEPLOYED',
            'external_key_custody':'NOT_DEPLOYED',
            'runtime_process_authentication':'NOT_ESTABLISHED',
            'historical_rows_modified':0,'production_data_accessed':False,
            'historical_3569_population':'EXCLUDED',
            'production_activation_authorized':False,'promotion_authority':'NONE',
            'verdict':'NO_GO'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--json",action="store_true");parser.parse_args()
    out=run();print(json.dumps(out,sort_keys=True,indent=2));return 0 if out['ok'] else 2
if __name__=='__main__':raise SystemExit(main())
