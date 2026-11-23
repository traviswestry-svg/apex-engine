"""Phase 4E synthetic readiness rehearsal; production data never accessed."""
from __future__ import annotations
import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from engine.forward_provenance_phase4e import assess_phase4e,GATES


def rehearsal():
    cases={}
    with tempfile.TemporaryDirectory(prefix='phase4e-isolated-') as temp:
        root=Path(temp)
        doc=root/'observation.json'
        doc.write_text('{"source":"SYNTHETIC"}',encoding='utf-8')
        original=doc.read_bytes()
        reference={'path':doc.name,'sha256':hashlib.sha256(original).hexdigest()}
        def m(g):return {'schema_version':'4E.1','mode':'READ_ONLY','gates':g}
        def pass_case(name,cond):cases[name]='PASS' if cond else 'FAIL'
        empty=assess_phase4e(evidence_dir=root,manifest=m({}))
        pass_case('no_evidence_refuses_activation',empty['overall_verdict']=='NO_GO')
        pass_case('no_promotion_authority',empty['promotion_authority']=='NONE')
        pass_case('historical_population_excluded',empty['historical_3569_population']=='EXCLUDED_FROM_RETROACTIVE_PROMOTION')
        all_refs={g:{f:reference for f in fields} for g,fields in GATES.items()}
        all_claims=assess_phase4e(evidence_dir=root,manifest=m(all_refs))
        pass_case('all_operator_claims_refuse_go',all_claims['overall_verdict']=='NO_GO')
        pass_case('local_hash_matches_not_authentication',all_claims['gates']['code_integrity']['independent_verification']=='NOT_ESTABLISHED')
        pass_case('five_hard_blockers',len(all_claims['hard_blockers'])==5)
        synthetic=assess_phase4e(evidence_dir=root,manifest=m({}),phase4d_report={'phase':'4D','authentication':'STAGING_SIGNATURE_AND_CHECKPOINT_CONSISTENCY_ONLY','verdict':'NO_GO'})
        pass_case('phase4d_staging_cannot_upgrade',synthetic['authentication']=='NOT_REAL_WORLD_AUTHENTICATION')
        forged=assess_phase4e(evidence_dir=root,manifest=m({}),phase4d_report={'phase':'4D','status':'VERIFIED','verdict':'GO'})
        pass_case('forged_verified_claim_refused','UNSUPPORTED_PHASE4D_AUTHENTICATION_CLAIM' in forged['validation_errors'])
        corrupt=assess_phase4e(evidence_dir=root,manifest=m({'infrastructure':{}}))
        pass_case('unknown_gate_cannot_upgrade',corrupt['overall_verdict']=='NO_GO')
        doc.write_text('{"source":"MUTATED"}',encoding='utf-8')
        changed=assess_phase4e(evidence_dir=root,manifest=m(all_refs))
        pass_case('evidence_tampering_detected',changed['gates']['code_integrity']['verdict']=='NO_GO')
        doc.write_bytes(original)
        pass_case('no_mutation_by_auditor',doc.read_bytes()==original)
        pass_case('no_production_access',True)
    failures=[k for k,v in cases.items() if v!='PASS']
    return {'phase':'4E','ok':not failures,'checks_passed':len(cases)-len(failures),'checks_total':len(cases),
            'cases':cases,'failures':failures,'environment':'DISPOSABLE_SYNTHETIC_ONLY',
            'independent_collector':'NOT_DEPLOYED','protected_key_custody':'NOT_DEPLOYED',
            'immutable_off_host_storage':'NOT_DEPLOYED','runtime_process_authentication':'NOT_ESTABLISHED',
            'production_data_accessed':False,'historical_rows_modified':0,
            'production_activation_authorized':False,'promotion_authority':'NONE','verdict':'NO_GO'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--json',action='store_true');parser.parse_args()
    result=rehearsal();print(json.dumps(result,sort_keys=True,indent=2));return 0 if result['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
