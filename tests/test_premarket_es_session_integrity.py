"""Regression coverage for ES session isolation and close proxy."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from engine.premarket_feature_provider import derive_es_features

ET = ZoneInfo('America/New_York')

def bar(at, price):
    return {'t': int(at.timestamp()*1000), 'c': price, 'h': price+1, 'l': price-1, 'v': 10}

def context():
    overnight = datetime(2026, 10, 29, 18, tzinfo=ET)
    prior = datetime(2026, 10, 29, 9, 30, tzinfo=ET)
    older = datetime(2026, 10, 28, 9, 30, tzinfo=ET)
    return {'status':'ok', 'ticker':'ES',
        'bars':[bar(overnight + timedelta(minutes=5*i), 7000+i*.1) for i in range(168)],
        'prior_rth_bars': [bar(older+timedelta(minutes=5*i), 6800+i*.1) for i in range(78)] +
                          [bar(prior+timedelta(minutes=5*i), 6900+i*.1) for i in range(78)]}

def derive(ctx):
    return derive_es_features(ctx, decision_at='2026-10-30T08:05:00-04:00', target_session_date='2026-10-30')

def test_mixed_dates_select_latest_complete_session():
    ctx=context()
    mixed=derive(ctx)
    ctx['prior_rth_bars']=ctx['prior_rth_bars'][78:]
    isolated=derive(ctx)
    assert mixed['prior_day_range_position']['value']==isolated['prior_day_range_position']['value']

def test_missing_last_rth_bar_abstains():
    ctx=context()
    ctx['prior_rth_bars']=ctx['prior_rth_bars'][:-1]
    assert 'prior_day_range_position' not in derive(ctx)

def test_most_recent_partial_session_does_not_fallback_to_older():
    ctx=context()
    ctx['prior_rth_bars']=ctx['prior_rth_bars'][:78]+ctx['prior_rth_bars'][78:108]
    assert 'prior_day_range_position' not in derive(ctx)

def test_duplicate_prior_timestamp_abstains():
    ctx=context()
    ctx['prior_rth_bars'].append(ctx['prior_rth_bars'][-1])
    assert 'prior_day_range_position' not in derive(ctx)
