import os
import tempfile

from engine import feature_store_db as db
from engine.dashboard_evidence import build_dashboard_evidence
from engine.feature_store import Feature, build_pre_decision_vector


def setup_function(_):
    fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    db._DB_PATH = path; db._DB_READY = False; assert db.init_db()


def teardown_function(_):
    path = db._DB_PATH; db._DB_READY = False
    try: os.unlink(path)
    except OSError: pass


def test_dashboard_preserves_current_evidence_and_guardrails():
    current = {
        'chain_quality': {'quality_score': 91},
        'chain_quality_gate': {'action': 'ALLOW', 'multiplier': .91},
        'intraday_event_regime': {'state': 'EVENT_DISCOVERY'},
        'confidence_attribution': {'available': True, 'effective_confidence': 72},
    }
    out = build_dashboard_evidence(current_result=current, ticker='SPX')
    assert out['quality']['quality_score'] == 91
    assert out['event_regime']['state'] == 'EVENT_DISCOVERY'
    assert out['confidence_attribution']['effective_confidence'] == 72
    assert out['guardrails']['read_only'] is True
    assert out['guardrails']['similarity_is_trade_signal'] is False
    assert out['guardrails']['learning_auto_activation'] is False


def test_dashboard_uses_latest_ticker_sample_only():
    for ticker, sid in [('QQQ','q'), ('SPX','s')]:
        dec = '2026-07-15T10:00:00'
        vec = build_pre_decision_vector(
            sample_id=sid, decision_time=dec, ticker=ticker,
            session_date='2026-07-15',
            features=[Feature('ici', 70, dec, 'test')]
        )
        assert db.write_features(vec)
    out = build_dashboard_evidence(current_result={}, ticker='SPX')
    assert out['latest_sample']['sample_id'] == 's'
    assert out['ticker'] == 'SPX'


def test_dashboard_files_expose_evidence_panel():
    root = os.path.dirname(os.path.dirname(__file__))
    template = open(os.path.join(root, 'templates', 'apex_os.html'), encoding='utf-8').read()
    js = open(os.path.join(root, 'static', 'js', 'apex_os.js'), encoding='utf-8').read()
    assert 'id="evidenceCard"' in template
    assert 'id="evidenceConfidence"' in template
    assert '/api/apex10/evidence' in js
    assert 'Similarity is historical evidence—not a trade signal' in template
