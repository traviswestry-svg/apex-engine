"""Run only isolated Phase 4C recovery tests (no production dependencies)."""
from __future__ import annotations
import argparse
import json
import unittest


def run():
    from tests.test_forward_provenance_phase4c import Phase4CTests
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Phase4CTests)
    result=unittest.TestResult(); suite.run(result)
    passed=result.testsRun-len(result.failures)-len(result.errors)
    return {'phase':'4C','ok':result.wasSuccessful(),'checks_passed':passed,
            'checks_total':result.testsRun,
            'failures':[str(t) + ': ' + e.splitlines()[-1] for t,e in result.failures+result.errors],
            'environment':'DISPOSABLE_SYNTHETIC_ONLY',
            'storage':'LOCAL_SQLITE_OFF_HOST_SIMULATION_NOT_INDEPENDENT',
            'durable_replay_register':'STAGING_SQLITE_ONLY',
            'external_anchor':'CALLER_SUPPLIED_NOT_INDEPENDENTLY_AUTHENTICATED',
            'external_key_custody':'NOT_DEPLOYED',
            'independently_operated_collector':'NOT_DEPLOYED',
            'runtime_process_authentication':'NOT_ESTABLISHED',
            'historical_3569_population':'EXCLUDED',
            'production_data_accessed':False,'historical_rows_modified':0,
            'production_activation_authorized':False,'promotion_authority':'NONE','verdict':'NO_GO'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--json',action='store_true');parser.parse_args()
    report=run(); print(json.dumps(report,sort_keys=True,indent=2))
    return 0 if report['ok'] else 2

if __name__=='__main__':raise SystemExit(main())
