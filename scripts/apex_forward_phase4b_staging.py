"""Phase 4B staging signer rehearsal; no live keys, no production signing."""
from __future__ import annotations
import argparse
import json
import unittest


def run():
    from tests.test_forward_provenance_phase4b import Phase4BTests
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Phase4BTests)
    result=unittest.TestResult()
    suite.run(result)
    passed=result.testsRun - len(result.failures) - len(result.errors)
    return {'phase':'4B','ok':result.wasSuccessful(),'checks_passed':passed,
            'checks_total':result.testsRun,'failures':[str(x[0]) for x in result.failures+result.errors],
            'environment':'DISPOSABLE_SYNTHETIC_ONLY',
            'authentication':'TEST_SIGNATURES_NOT_REAL_WORLD_AUTHENTICATION',
            'external_key_custody':'NOT_DEPLOYED','durable_replay_register':'NOT_IMPLEMENTED',
            'independently_operated_collector':'NOT_DEPLOYED',
            'runtime_process_authentication':'NOT_ESTABLISHED',
            'production_activation_authorized':False,'promotion_authority':'NONE','verdict':'NO_GO',
            'historical_3569_population':'EXCLUDED'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json',action='store_true')
    parser.parse_args()
    result=run()
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result['ok'] else 2
if __name__=='__main__':raise SystemExit(main())
