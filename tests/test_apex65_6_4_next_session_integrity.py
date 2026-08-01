import datetime as dt
from zoneinfo import ZoneInfo

from engine.session_intelligence import classify_session
from engine.morning_brief import generate_morning_brief

ET = ZoneInfo('America/New_York')


def _kwargs(now):
    ms=lambda h,m,d=0:int((now.replace(hour=h,minute=m,second=0,microsecond=0)+dt.timedelta(days=d)).timestamp()*1000)
    daily=[{'t':ms(16,0,-2),'o':7400,'h':7420,'l':7390,'c':7410}, {'t':ms(16,0,-1),'o':7410,'h':7440,'l':7400,'c':7430}]
    intr=[]
    for i in range(60):
        t=now.replace(hour=9,minute=30,second=0,microsecond=0)+dt.timedelta(minutes=i)-dt.timedelta(days=1)
        intr.append({'t':int(t.timestamp()*1000),'o':7430,'h':7440,'l':7420,'c':7435,'v':100})
    return dict(canonical_ms={'price':7435.0}, flow_snapshot={}, daily_bars=daily, intraday_1m_bars=intr,
                straddle=40.0, iv=None, time_to_close_frac=0.01, atr_val=50.0, adr_val=55.0)


def test_weekend_session_uses_last_completed_trading_day():
    sc=classify_session(dt.datetime(2026,8,1,11,0,tzinfo=ET)).to_dict()
    assert sc['source_session_date']=='2026-07-31'
    assert sc['target_session_date']=='2026-08-03'


def test_next_session_suppresses_prior_or_ib():
    now=dt.datetime(2026,8,1,11,0,tzinfo=ET)
    sc=classify_session(now).to_dict()
    payload=generate_morning_brief(session_context=sc, api_key='', **_kwargs(now))
    levels=payload['structured']['levels']
    opening={'or5_high','or5_low','or15_high','or15_low','ib_high','ib_low','ib_extension'}
    assert all(l['price']=='[FEED REQUIRED]' for l in levels if l['kind'] in opening)
    assert not any(r['kind'] in opening for r in payload['structured']['ranked'])
