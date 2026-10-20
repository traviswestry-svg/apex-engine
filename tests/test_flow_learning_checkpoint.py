from engine.flow_learning_checkpoint import CheckpointStore


def test_resume_and_no_rewind(tmp_path):
    store = CheckpointStore(str(tmp_path / 'cursor.db'))
    assert store.read('2026-10-20', 'source-v1').next_index == 0
    assert store.advance('2026-10-20', 'source-v1', 0, 12)
    assert store.read('2026-10-20', 'source-v1').next_index == 12
    assert not store.advance('2026-10-20', 'source-v1', 0, 15)
    assert store.advance('2026-10-20', 'source-v1', 12, 20, completed=True)
    assert store.read('2026-10-20', 'source-v1').completed
    assert not store.advance('2026-10-20', 'source-v1', 20, 21)


def test_source_change_isolated(tmp_path):
    store = CheckpointStore(str(tmp_path / 'cursor.db'))
    assert store.advance('2026-10-20', 'source-v1', 0, 10)
    assert store.read('2026-10-20', 'source-v2').next_index == 0


def test_invalid_rewind_rejected(tmp_path):
    store = CheckpointStore(str(tmp_path / 'cursor.db'))
    try:
        store.advance('2026-10-20', 'source-v1', 4, 3)
    except ValueError:
        pass
    else:
        raise AssertionError('rewind must be rejected')
