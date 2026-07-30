from engine.daily_key_levels import (
    ExpectedMove, FEED_REQUIRED, GammaRegime, GammaStructure,
    KeyLevel, LevelKind, LevelSource, RankedLevel, TradeMapLine,
    render_brief_sections,
)


def _gamma():
    return GammaStructure(
        flip=FEED_REQUIRED,
        zero_gamma=FEED_REQUIRED,
        call_wall=7450.0,
        put_wall=7400.0,
        hi_gamma=7435.0,
        lo_gamma=7000.0,
        vol_trigger=FEED_REQUIRED,
        regime=GammaRegime.NEUTRAL_GAMMA,
        dealer_delta=FEED_REQUIRED,
    )


def test_string_expected_move_confidence_does_not_crash_renderer():
    level = KeyLevel(LevelKind.PDH, 7450.84, LevelSource.POLYGON, label="Prev Day High")
    em = ExpectedMove(
        spot=7411.17,
        em_1sigma=27.5825,
        upper=7438.7525,
        lower=7383.5875,
        em_2sigma=55.165,
        expected_daily_range=55.165,
        straddle_implied=27.5825,
        iv_implied=FEED_REQUIRED,
        atr=FEED_REQUIRED,
        avg_daily_range=FEED_REQUIRED,
        confidence="HIGH",
        confidence_basis="two-sided ATM mid",
    )
    ranked = [RankedLevel(level=level, importance=0.616, proximity=39.67)]
    text = render_brief_sections(7411.17, [level], _gamma(), em, [], ranked)
    assert "conf=HIGH" in text
    assert "7,450.84" in text
    assert "importance=0.616" in text


def test_non_numeric_values_are_rendered_instead_of_float_formatted():
    level = KeyLevel(LevelKind.GAMMA_FLIP, FEED_REQUIRED, LevelSource.GAMMA_PROVIDER, label="Gamma Flip")
    em = ExpectedMove(
        spot=7411.17,
        em_1sigma=FEED_REQUIRED,
        upper=FEED_REQUIRED,
        lower=FEED_REQUIRED,
        em_2sigma=FEED_REQUIRED,
        expected_daily_range=FEED_REQUIRED,
        straddle_implied=FEED_REQUIRED,
        iv_implied=FEED_REQUIRED,
        atr=FEED_REQUIRED,
        avg_daily_range=FEED_REQUIRED,
        confidence="NOT_APPLICABLE",
    )
    text = render_brief_sections(7411.17, [level], _gamma(), em, [], [])
    assert "conf=NOT_APPLICABLE" in text
    assert "[FEED REQUIRED]" in text
