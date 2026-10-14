import sqlite3
from engine.canonical_settlement_eligibility_38 import audit


def test_exact_identity_partition_and_no_writes(tmp_path):
    path = str(tmp_path / 'test.db')
    with sqlite3.connect(path) as db:
        for name in ('flow_features','flow_labels','flow_sample_excursions','flow_sample_pl_lifecycle'):
            db.execute(f'CREATE TABLE {name}(sample_id TEXT PRIMARY KEY, session_date TEXT, state TEXT, reason TEXT)')
        for sid in ('a','b','c','d'):
            db.execute('INSERT INTO flow_features(sample_id,session_date) VALUES (?,?)',(sid,'2026-10-13'))
        for sid in ('a','b','c'):
            db.execute('INSERT INTO flow_sample_pl_lifecycle(sample_id,state,reason) VALUES (?,?,?)',(sid,'AWAITING_REAL_PL','NO_PL'))
        for sid in ('a','d'):
            db.execute('INSERT INTO flow_sample_excursions(sample_id) VALUES (?)',(sid,))
        for sid in ('a','b'):
            db.execute('INSERT INTO flow_labels(sample_id) VALUES (?)',(sid,))
    before = sqlite3.connect(path).execute('SELECT COUNT(*) FROM flow_labels').fetchone()[0]
    r = audit(path)
    assert r['state']=='READY'
    c=r['counts']
    assert (c['features'],c['labelled'],c['unlabelled'])==(4,2,2)
    assert (c['excursion_labelled'],c['excursion_unlabelled'])==(1,1)
    assert c['label_without_excursion']==1
    assert c['pending_with_lifecycle_no_excursion']==1
    assert c['pending_without_lifecycle_no_excursion']==0
    assert r['writes_evidence'] is False and r['execution_authority'] is False
    assert sqlite3.connect(path).execute('SELECT COUNT(*) FROM flow_labels').fetchone()[0]==before


def test_missing_schema_fails_closed(tmp_path):
    path=str(tmp_path/'empty.db')
    sqlite3.connect(path).close()
    assert audit(path)['state']=='MISSING_TABLES'
