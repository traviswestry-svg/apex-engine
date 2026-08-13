from engine.daily_key_levels import FEED_REQUIRED, present
from engine.daily_key_levels_adapters import CanonicalMarketDataAdapter
from engine.morning_brief import build_deterministic


def test_present_rejects_none_as_missing_feed_value():
    assert present(None) is False
    assert present(FEED_REQUIRED) is False
    assert present(1.25) is True


def test_market_data_adapter_normalizes_optional_none_values():
    md = CanonicalMarketDataAdapter(
        daily_bars=[], intraday_1m_bars=[],
        spot=None, straddle=None, iv=None, time_to_close_frac=None,
        atr_val=None, adr_val=None,
    )
    assert md.spot() is FEED_REQUIRED
    assert md.atm_straddle() is FEED_REQUIRED
    assert md.atm_iv() is FEED_REQUIRED
    assert md.time_to_close_frac() is FEED_REQUIRED
    assert md.atr() is FEED_REQUIRED
    assert md.avg_daily_range() is FEED_REQUIRED


def test_closed_market_brief_deterministic_layer_accepts_all_optional_none():
    dkl, sections, context = build_deterministic(
        canonical_ms={}, flow_snapshot={}, daily_bars=[], intraday_1m_bars=[],
        overnight_bars=[], es_daily_bars=[], es_spot=None, proxy_instrument='ES',
        straddle=None, iv=None, time_to_close_frac=None, atr_val=None, adr_val=None,
    )
    assert dkl is not None
    assert '[FEED REQUIRED]' in sections
    assert context['expected_move']['one_sigma'] == '[FEED REQUIRED]'
