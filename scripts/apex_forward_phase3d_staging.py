"""Disposable Phase 3D operational report rehearsal, without production files."""
from __future__ import annotations

import argparse
import json
import unittest


def rehearse():
    from tests.test_forward_provenance_phase3d import Phase3DTests
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Phase3DTests)
    result=unittest.TestResult()
    suite.run(result)
    return {'ok':result.wasSuccessful(),'phase':'3D','environment':'DISPOSABLE_SYNTHETIC_ONLY',
            'checks_passed':result.testsRun-len(result.failures)-len(result.errors),
            'total_checks':result.testsRun,'failures':[str(x[0]) for x in result.failures+result.errors],
            'production_data_accessed':False,'historical_rows_modified':0,
            'promotion_authority':'NONE', 'authentication':'NOT_REAL_WORLD_AUTHENTICATION'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--json',action='store_true')
    p.parse_args()
    out=rehearse()
    print(json.dumps(out,indent=2,sort_keys=True))
    return 0 if out['ok'] else 2

if __name__=='__main__':raise SystemExit(main())
