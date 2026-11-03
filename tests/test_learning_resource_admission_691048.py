from engine.learning_resource_admission import assess_resource_admission


def snapshot(raw=80, noninactive=50, psi=0, severity='NORMAL'):
    return dict(raw_usage_pct=raw, estimated_noninactive_file_usage_pct=noninactive,
                psi_some_avg10=psi, severity=severity)


def test_admits_bounded_usage():
    assert assess_resource_admission(snapshot()) == 'ADMITTED'


def test_blocks_high_raw_even_with_reclaimable_cache():
    assert assess_resource_admission(snapshot(raw=96)) == 'DEFERRED_MEMORY_PRESSURE'


def test_blocks_noninactive_and_psi():
    assert assess_resource_admission(snapshot(noninactive=80)) == 'DEFERRED_MEMORY_PRESSURE'
    assert assess_resource_admission(snapshot(psi=3)) == 'DEFERRED_MEMORY_PRESSURE'


def test_unknown_fails_closed():
    assert assess_resource_admission({}) == 'DEFERRED_MEMORY_UNKNOWN'
    assert assess_resource_admission(None) == 'DEFERRED_MEMORY_UNKNOWN'


def test_pressure_severity_blocks():
    assert assess_resource_admission(snapshot(severity='CRITICAL')) == 'DEFERRED_MEMORY_PRESSURE'
