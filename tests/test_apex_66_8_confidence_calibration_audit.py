import json
from engine.evidence_pipeline import _connect
from engine.confidence_calibration_audit import build_confidence_calibration_audit


def _seed(path, n=20, confidence=80.0, wins=10):
    with _connect(path) as c:
        for i in range(n):
            did=f'd{i}'
            won=i < wins
            direction='BULLISH'
            snap={
                'setup':'ORB_RECLAIM',
                'gamma_regime':'POSITIVE',
                'market_regime':'TREND',
                'trade_horizon_intelligence':{'horizons':{
                    'SCALP':{'direction':direction,'confidence':confidence},
                    'INTRADAY':{'direction':direction,'confidence':confidence-5},
                }},
            }
            c.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",(did,f'2026-08-{1+i//4:02d}T14:{i%60:02d}:00+00:00','SPX','MARKET_OPEN',direction,'TRADE',6400+i,confidence,1,json.dumps(snap),'GRADED'))
            c.execute("INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",(did,f'2026-08-{1+i//4:02d}T14:{(i+5)%60:02d}:00+00:00','GRADED',None,300,json.dumps({'won':won,'direction_correct':won,'directional_move':2 if won else -2,'mfe':4,'mae':-2})))


def test_audit_detects_overconfidence(tmp_path):
    p=tmp_path/'e.db'; _seed(p, n=20, confidence=80, wins=10)
    out=build_confidence_calibration_audit(path=p, minimum_sample=20)
    assert out['status']=='READY'
    assert out['overall']['mean_stated_confidence']==80.0
    assert out['overall']['observed_hit_rate']==50.0
    assert out['overall']['calibration_gap_points']==30.0
    assert out['assessment']['state']=='OVERCONFIDENT'
    assert out['guardrails']['writes_calibrated_confidence'] is False


def test_reliability_bucket_and_reference_are_audit_only(tmp_path):
    p=tmp_path/'e.db'; _seed(p, n=20, confidence=80, wins=12)
    out=build_confidence_calibration_audit(path=p, minimum_sample=20)
    b=next(x for x in out['reliability_buckets'] if x['bucket']=='80-89')
    assert b['sample_size']==20
    assert b['observed_hit_rate']==60.0
    assert b['qualified'] is True
    assert b['audit_reference_probability'] is not None
    assert out['guardrails']['automatic_recalibration'] is False


def test_horizon_uses_horizon_confidence(tmp_path):
    p=tmp_path/'e.db'; _seed(p, n=20, confidence=80, wins=14)
    out=build_confidence_calibration_audit(path=p, minimum_sample=20)
    h={x['value']:x for x in out['breakdowns']['horizon']}
    assert h['SCALP']['mean_stated_confidence']==80.0
    assert h['INTRADAY']['mean_stated_confidence']==75.0
    assert h['SCALP']['sample_size']==20


def test_collecting_before_minimum_sample(tmp_path):
    p=tmp_path/'e.db'; _seed(p, n=5, confidence=70, wins=4)
    out=build_confidence_calibration_audit(path=p, minimum_sample=20)
    assert out['status']=='COLLECTING'
    assert out['assessment']['quality']=='INSUFFICIENT_DATA'


def test_no_graded_history_waits(tmp_path):
    p=tmp_path/'e.db'
    with _connect(p):
        pass
    out=build_confidence_calibration_audit(path=p, minimum_sample=20)
    assert out['status']=='WAITING_FOR_GRADED_OUTCOMES'
    assert out['overall']['sample_size']==0
