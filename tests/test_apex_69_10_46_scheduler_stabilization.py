from engine.scanner_scheduler_accounting import bounded_scheduler_sleep, update_freshness_episode


def test_no_busy_spin_when_stale():
    assert bounded_scheduler_sleep(0, freshness_exhausted=True) == 5.0
    assert bounded_scheduler_sleep(2, freshness_exhausted=True) == 5.0
    assert bounded_scheduler_sleep(20, freshness_exhausted=True) == 20.0


def test_normal_cadence_unchanged():
    assert bounded_scheduler_sleep(0, freshness_exhausted=False) == 0
    assert bounded_scheduler_sleep(92.57, freshness_exhausted=False) == 92.57


def test_episode_counts_only_new_streaks():
    state = {}
    for exhausted in (False, True, True, True, False, True):
        update_freshness_episode(state, exhausted=exhausted, now_iso='2026-10-26T12:00:00+00:00')
    assert state['scheduler_cycles_accounted'] == 6
    assert state['freshness_budget_exhausted_cycles'] == 4
    assert state['freshness_budget_exhausted_episodes'] == 2
    assert state['freshness_budget_exhausted_active'] is True


def test_invalid_zero_minimum_is_bounded():
    assert bounded_scheduler_sleep(0, freshness_exhausted=True, min_exhausted_sleep_seconds=0) == 1.0
    assert bounded_scheduler_sleep(0, freshness_exhausted=True, min_exhausted_sleep_seconds=999) == 30.0


def test_memory_trend_bounded_and_does_not_claim_leak():
    from engine.runtime_memory_pressure import bounded_memory_trend
    trend = bounded_memory_trend([(10, 100), (70, 150)], current=900,
                                 noninactive=200, observed_monotonic=80)
    assert trend['samples'] == 2
    assert trend['noninactive_delta_bytes'] == 100
    assert trend['observation_span_seconds'] == 70
    assert trend['leak_confirmed'] is False
