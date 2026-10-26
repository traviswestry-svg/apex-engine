from engine.adaptive_morning_forecast_calibration import calibrate


def row(i, **overrides):
    d = dict(session_date=f'2026-09-{i:02d}', forecast_provenance_verified=True,
             outcome_complete=True, forecast_spot=100, forecast_one_sigma=10,
             actual_high=115, actual_low=95)
    d.update(overrides)
    return d


def test_no_history_fails_closed():
    assert calibrate(target_date='2026-10-26', forecast_spot=100, forecast_one_sigma=10, history=[])['candidate'] is None


def test_future_and_unverified_excluded():
    rows = [row(i) for i in range(1, 21)]
    rows[0]['forecast_provenance_verified'] = False
    rows.append(row(22, session_date='2026-10-27'))
    assert calibrate(target_date='2026-10-26', forecast_spot=100, forecast_one_sigma=10, history=rows)['candidate'] is None


def test_ready_and_bounded():
    rows = [row(i, actual_high=150, actual_low=130) for i in range(1, 21)]
    result = calibrate(target_date='2026-10-26', forecast_spot=100, forecast_one_sigma=10, history=rows)
    assert result['state'] == 'SHADOW_CANDIDATE_READY'
    assert result['candidate']['center_offset_sigma'] == .5
    assert result['candidate']['width_factor'] == 1
    assert result['candidate']['center'] == 105


def test_duplicate_dates_do_not_inflate_sample():
    rows = [row(i) for i in range(1, 20)] + [row(19)]
    assert calibrate(target_date='2026-10-26', forecast_spot=100, forecast_one_sigma=10, history=rows)['eligible_sessions'] == 18


def test_invalid_and_missing_outcome_rejected():
    rows = [row(i) for i in range(1, 21)]
    rows[0]['outcome_complete'] = False
    assert calibrate(target_date='2026-10-26', forecast_spot=100, forecast_one_sigma=10, history=rows)['candidate'] is None
    assert calibrate(target_date='2026-10-26', forecast_spot=100, forecast_one_sigma=0, history=rows)['state'] == 'INVALID_FORECAST_INPUT'


def test_walk_forward_uses_prior_only():
    from engine.adaptive_morning_forecast_calibration import walk_forward
    from datetime import date, timedelta
    rows = []
    for i in range(25):
        day = (date(2026, 9, 1) + timedelta(days=i)).isoformat()
        rows.append(row(1, session_date=day))
    outcome = walk_forward(rows)
    assert outcome['holdout_sessions'] == 5
    assert outcome['rows'][0]['session_date'] == '2026-09-21'
    assert outcome['promotion_authority'] is False
