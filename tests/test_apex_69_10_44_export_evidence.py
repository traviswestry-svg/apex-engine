import csv
import io
import json
from datetime import datetime, timedelta, timezone
import pytest
from engine.execution import paper_execution_foundation as foundation
from engine.execution import traderspost_export_evidence as export

CONTRACT = {'ticker':'SPX','strike':7000,'side':'CALL','expiry':'2026-10-22'}
COLS = {s:s for s in export.REQUIRED}
WHEN = (datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()


def setup_db(tmp_path):
    path=tmp_path/'paper.sqlite3'
    foundation.bind_canonical_observation('life1','decision1',CONTRACT,
        trusted_reader=lambda did: {'decision_id':did,'record_id':did,
        'origin':'canonical_decision_store','contract':CONTRACT,'persisted':True},
        observed_at=WHEN, db_path=path)
    return path


def data(**changes):
    row=dict(event_id='e1',order_id='o1',event_type='ENTRY_FILL',decision_id='decision1',
             observed_at=WHEN,contract_json=json.dumps(CONTRACT),quantity='1',price='2.50')
    row.update(changes)
    buffer=io.StringIO(); writer=csv.DictWriter(buffer,fieldnames=COLS);writer.writeheader();writer.writerow(row)
    return buffer.getvalue().encode()


def test_quarantined_and_restart_readable(tmp_path):
    path=setup_db(tmp_path)
    result=export.stage_csv(data(),column_map=COLS,lifecycle_by_decision={'decision1':'life1'},db_path=path)
    assert result['staged']==1 and not result['fill_verified']
    assert export.export_inbox_health(db_path=path)['quarantined_csv_events']==1
    assert foundation.snapshot(db_path=path)['verified_closed']==0
    with pytest.raises(ValueError,match='DUPLICATE'):
        export.stage_csv(data(),column_map=COLS,lifecycle_by_decision={'decision1':'life1'},db_path=path)


@pytest.mark.parametrize('change', [
    {'decision_id':'wrong'}, {'contract_json':'{"ticker":"SPY"}'},
    {'quantity':'0'}, {'price':'NaN'}, {'event_type':'SENT'},
    {'observed_at':'2099-01-01T00:00:00Z'},
])
def test_invalid_export_never_staged(tmp_path,change):
    path=setup_db(tmp_path)
    with pytest.raises(ValueError):
        export.stage_csv(data(**change),column_map=COLS,lifecycle_by_decision={'decision1':'life1'},db_path=path)
    assert export.export_inbox_health(db_path=path)['quarantined_csv_events']==0


def test_invalid_mapping_and_size(tmp_path):
    path=setup_db(tmp_path)
    with pytest.raises(ValueError):
        export.stage_csv(data(), column_map={}, lifecycle_by_decision={},db_path=path)
    with pytest.raises(ValueError):
        export.stage_csv(b'x'*(export.MAX_BYTES+1),column_map=COLS,lifecycle_by_decision={},db_path=path)
