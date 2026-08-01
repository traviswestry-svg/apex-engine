from engine.daily_key_levels import FEED_REQUIRED, present
from engine.daily_key_levels_adapters import CanonicalMarketDataAdapter
from engine.morning_brief import generate_morning_brief


def test_adapter_normalizes_none_optionals_to_feed_required():
    md = CanonicalMarketDataAdapter(
        daily_bars=[], intraday_1m_bars=[], spot=None, straddle=None, iv=None,
        time_to_close_frac=None, atr_val=None, adr_val=None,
    )
    assert md.spot() is FEED_REQUIRED
    assert md.atm_straddle() is FEED_REQUIRED
    assert md.atm_iv() is FEED_REQUIRED
    assert md.time_to_close_frac() is FEED_REQUIRED
    assert md.atr() is FEED_REQUIRED
    assert md.avg_daily_range() is FEED_REQUIRED
    assert not present(md.spot())


def test_weekend_morning_brief_degrades_without_expected_move_inputs():
    out = generate_morning_brief(
        cache={}, narrative_cache={}, api_key='',
        session_context={
            'state': 'CLOSED', 'brief_mode': 'NEXT_SESSION_PREP',
            'label': 'Weekend', 'market_open': False,
        },
        canonical_ms={}, flow_snapshot={}, daily_bars=[], intraday_1m_bars=[],
        straddle=None, iv=None, time_to_close_frac=None,
        atr_val=None, adr_val=None, vp_extra={}, overnight_bars=[],
        es_daily_bars=[], es_spot=None, proxy_instrument='ES',
    )
    assert out['ok'] is True
    structured = out['structured']
    assert structured['expected_move']['one_sigma'] == '[FEED REQUIRED]'
    assert structured['expected_move']['upper'] == '[FEED REQUIRED]'
    assert structured['expected_move']['lower'] == '[FEED REQUIRED]'
    assert '[FEED REQUIRED]' in out['markdown']
