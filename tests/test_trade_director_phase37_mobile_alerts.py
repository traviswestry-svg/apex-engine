from datetime import datetime, timezone

import engine.trade_director_mobile_momentum_alerts as m


def setup_function():
    m.DB_PATH = m.Path('/tmp/apex_phase37_test.db')
    try: m.DB_PATH.unlink()
    except FileNotFoundError: pass


def snap(**extra):
    base = {
        'market_open': True, 'data_fresh': True, 'risk_eligible': True, 'spread_ok': True,
        'direction': 'CALL', 'confidence': 88, 'trigger_state': 'WAITING',
        'entry_quality': {'entry_quality_score': 93, 'entry_quality_grade': 'A+'},
        'trade_function_router': {'selected_function': {'function': 'MOMENTUM_BURST'}},
        'trigger_level': 6382.5,
    }
    base.update(extra); return base


def test_primed_classification():
    assert m.classify_alert_stage(snap())['stage'] == 'MOMENTUM_PRIMED'


def test_entry_window_open():
    assert m.classify_alert_stage(snap(trigger_state='CONFIRMED'))['stage'] == 'ENTRY_WINDOW_OPEN'


def test_watch_is_lower_threshold():
    s = snap(confidence=74, entry_quality={'entry_quality_score': 78, 'entry_quality_grade': 'B+'})
    assert m.classify_alert_stage(s)['stage'] == 'MOMENTUM_WATCH'


def test_take_profit_from_phase36():
    s = snap(momentum_lifecycle={'recommendation': 'TAKE_PROFIT', 'premium_change': 2.15})
    assert m.classify_alert_stage(s)['stage'] == 'TAKE_PROFIT'


def test_exit_now_from_phase36():
    s = snap(momentum_lifecycle={'recommendation': 'EXIT_NOW', 'premium_change': -2.5})
    assert m.classify_alert_stage(s)['stage'] == 'EXIT_NOW'


def test_duplicate_suppression():
    sent=[]
    first=m.dispatch_mobile_alert(snap(), lambda x: sent.append(x) or True, now=datetime(2026,7,23,14,0,tzinfo=timezone.utc))
    second=m.dispatch_mobile_alert(snap(), lambda x: sent.append(x) or True, now=datetime(2026,7,23,14,1,tzinfo=timezone.utc))
    assert first['sent'] is True and second['suppressed'] is True and len(sent)==1


def test_failed_delivery_is_logged():
    out=m.dispatch_mobile_alert(snap(), lambda x: False, force=True)
    assert out['sent'] is False
    status=m.mobile_alert_status()
    assert status['failure_count']==1


def test_message_requires_manual_execution():
    state=m.classify_alert_stage(snap())
    text=m.format_alert(snap(), state)
    assert 'Manual execution and confirmation required' in text
