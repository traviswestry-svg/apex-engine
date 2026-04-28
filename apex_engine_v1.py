#!/usr/bin/env python3
from __future__ import annotations
print("🔥 APEX ENGINE VERSION 2.2 LIVE - ADAPTIVE EXIT ENGINE 🔥")

import base64, json, os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone, time
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import requests

POLYGON_API_KEY=os.getenv('POLYGON_API_KEY','').strip()
TELEGRAM_BOT_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
TELEGRAM_CHAT_ID=os.getenv('TELEGRAM_CHAT_ID','').strip()
ACCOUNT_SIZE=float(os.getenv('ACCOUNT_SIZE','60000'))
MAX_RISK_PER_TRADE=float(os.getenv('MAX_RISK_PER_TRADE','750'))
SEND_TELEGRAM=os.getenv('SEND_TELEGRAM','true').lower()=='true'
DASHBOARD_FILE=os.getenv('DASHBOARD_FILE','dashboard.json')
ALERT_CACHE_FILE=os.getenv('ALERT_CACHE_FILE','sent_alerts.json')
REQUEST_TIMEOUT=int(os.getenv('REQUEST_TIMEOUT','12'))
GITHUB_TOKEN=os.getenv('GITHUB_TOKEN','').strip()
GITHUB_REPO=os.getenv('GITHUB_REPO','').strip()
GITHUB_BRANCH=os.getenv('GITHUB_BRANCH','main').strip()
GITHUB_DASHBOARD_PATH=os.getenv('GITHUB_DASHBOARD_PATH','dashboard.json').strip()
POLYGON_BASE='https://api.polygon.io'
EASTERN=ZoneInfo('America/New_York')
TICKERS=['SPY','QQQ','SPX','NVDA','TSLA','META','MSFT','AAPL','AMZN','COIN','AMD','NFLX','PLTR','SMH','QCOM','NBIS']
ZERO_DTE_TICKERS={'SPY','QQQ'}

@dataclass
class Metrics:
    ticker:str; price:float; prev_close:float; volume:float; avg_volume_20:float; rel_volume:float
    ema8:float; ema21:float; ema50:float; ema200:float; rsi:float; atr:float; vwap:Optional[float]

@dataclass
class OptionPick:
    contract:str; expiration:str; strike:float; option_type:str; dte:int; estimated_entry:float
    stop_pct:float; risk_per_contract:float; max_contracts:int; spread_pct:Optional[float]
    volume:Optional[int]; open_interest:Optional[int]; liquidity_ok:bool; liquidity_note:str

@dataclass
class Idea:
    ticker:str; grade:str; score:int; trader_type:str; strategy:str; direction:str; status:str
    sniper_trigger:str; entry_zone:str; entry_range:str; exit_plan:str; stop_loss:str; targets:List[str]
    option_contract:str; estimated_option_entry:Optional[float]; dte:Optional[int]; max_contracts:int
    max_risk:float; price:float; rsi:float; rel_volume:float; notes:List[str]
    target_1:str=''; target_2:str=''; runner_rule:str=''; time_stop:str=''; profit_protection:str=''; exit_checklist:Optional[List[str]]=None

def log(x): print(x, flush=True)
def now_et(): return datetime.now(EASTERN)
def today_key(): return now_et().date().isoformat()
def session_name():
    n=now_et().time()
    if time(4,0)<=n<time(9,30): return 'PREMARKET'
    if time(9,30)<=n<=time(16,0): return 'MARKET_OPEN'
    return 'AFTER_HOURS'
def is_market_open(): return time(9,30)<=now_et().time()<=time(16,0)
def execution_window(strategy):
    n=now_et().time()
    if strategy=='0DTE': return is_market_open() and time(9,45)<=n<=time(15,30)
    return is_market_open() and time(9,45)<=n<=time(15,45)
def f(x,d=0.0):
    try: return float(x) if x is not None else d
    except Exception: return d
def rp(x): return round(float(x),2)

def ema(vals,period):
    vals=[f(v) for v in vals if v is not None]
    if not vals: return 0.0
    if len(vals)<period: return vals[-1]
    k=2/(period+1); e=sum(vals[:period])/period
    for p in vals[period:]: e=p*k+e*(1-k)
    return e

def rsi(vals,period=14):
    if len(vals)<=period: return 50.0
    gains=[]; losses=[]
    for i in range(1,len(vals)):
        diff=vals[i]-vals[i-1]; gains.append(max(diff,0)); losses.append(abs(min(diff,0)))
    ag=sum(gains[-period:])/period; al=sum(losses[-period:])/period
    if al==0: return 100.0
    return 100-(100/(1+(ag/al)))

def atr(h,l,c,period=14):
    if len(c)<2: return 0.0
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return sum(trs[-period:])/min(period,len(trs)) if trs else 0.0

def vwap_from_bars(bars):
    pv=0.0; vol=0.0
    for b in bars:
        v=f(b.get('v')); pv+=((f(b.get('h'))+f(b.get('l'))+f(b.get('c')))/3)*v; vol+=v
    return pv/vol if vol else None

def latest_day_bars(bars):
    if not bars: return []
    last=datetime.fromtimestamp(bars[-1].get('t',0)/1000, timezone.utc).astimezone(EASTERN).date()
    return [b for b in bars if datetime.fromtimestamp(b.get('t',0)/1000, timezone.utc).astimezone(EASTERN).date()==last]

class Polygon:
    def __init__(self,key): self.key=key
    def get(self,path,params=None,timeout=None):
        if not self.key:
            log('Missing POLYGON_API_KEY'); return None
        params=dict(params or {}); params['apiKey']=self.key
        try:
            r=requests.get(POLYGON_BASE+path,params=params,timeout=timeout or REQUEST_TIMEOUT)
            if r.status_code>=400:
                log(f'Polygon HTTP {r.status_code} for {path}: {r.text[:180]}'); return None
            return r.json()
        except requests.Timeout:
            log(f'Polygon timeout for {path}'); return None
        except Exception as e:
            log(f'Polygon error for {path}: {e}'); return None
    def daily(self,ticker,days=260):
        end=now_et().date(); start=end-timedelta(days=days*2)
        d=self.get(f'/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}',{'adjusted':'true','sort':'asc','limit':5000})
        return (d or {}).get('results') or []
    def intraday(self,ticker,mult=5,days=2):
        end=now_et().date(); start=end-timedelta(days=days)
        d=self.get(f'/v2/aggs/ticker/{ticker}/range/{mult}/minute/{start}/{end}',{'adjusted':'true','sort':'asc','limit':5000},10)
        return latest_day_bars((d or {}).get('results') or [])
    def options(self,ticker,direction,min_dte,max_dte,price,limit=100):
        if ticker=='SPX': return []
        today=now_et().date(); ct='call' if direction=='CALL' else 'put'
        params={'contract_type':ct,'expiration_date.gte':str(today+timedelta(days=min_dte)),'expiration_date.lte':str(today+timedelta(days=max_dte)),'strike_price.gte':round(max(1,price*.85),2),'strike_price.lte':round(price*(1.2 if direction=='CALL' else 1.15),2),'limit':limit}
        d=self.get(f'/v3/snapshot/options/{ticker}',params,12)
        return (d or {}).get('results') or []

def build_metrics(c,ticker):
    if ticker=='SPX':
        log('SPX skipped until Polygon Indices entitlement is added.'); return None,[]
    bars=c.daily(ticker)
    if len(bars)<60:
        log(f'Not enough daily bars for {ticker}'); return None,[]
    cl=[f(x.get('c')) for x in bars]; hi=[f(x.get('h')) for x in bars]; lo=[f(x.get('l')) for x in bars]; vol=[f(x.get('v')) for x in bars]
    avg20=sum(vol[-21:-1])/min(20,len(vol[-21:-1])) if len(vol)>21 else max(vol[-1],1)
    intra=c.intraday(ticker)
    return Metrics(ticker,cl[-1],cl[-2],vol[-1],avg20,vol[-1]/avg20 if avg20 else 1,ema(cl,8),ema(cl,21),ema(cl,50),ema(cl,200),rsi(cl),atr(hi,lo,cl),vwap_from_bars(intra)),intra

def trend(m):
    if m.price>m.ema50>m.ema200: return 'CALL'
    if m.price<m.ema50<m.ema200: return 'PUT'
    return None

def no_chase(m,direction,max_ext=.035):
    if m.ema21<=0: return False
    return ((m.price-m.ema21)/m.ema21<=max_ext) if direction=='CALL' else ((m.ema21-m.price)/m.ema21<=max_ext)

def sniper(m,bars,direction,strategy):
    if not execution_window(strategy): return 'WATCHLIST - OPEN CONFIRMATION NEEDED','Wait until regular-hours confirmation window',['market not in execution window']
    if len(bars)<8: return 'WAIT - NEED MORE INTRADAY BARS','Wait for 5-min structure',['not enough intraday bars']
    closes=[f(b.get('c')) for b in bars]; vols=[f(b.get('v')) for b in bars]
    last=bars[-1]; close=f(last.get('c')); high=f(last.get('h')); low=f(last.get('l')); v=f(last.get('v'))
    e8=ema(closes,8); e21=ema(closes,min(21,len(closes))); vw=m.vwap or vwap_from_bars(bars) or e21
    avgvol=sum(vols[-8:-1])/max(1,len(vols[-8:-1])); vol_ok=v>=avgvol*1.10 if avgvol else True
    if not no_chase(m,direction): return 'EXTENDED - DO NOT ENTER','Wait for pullback toward EMA21/VWAP',['daily price extended from EMA21']
    if direction=='CALL':
        if close>=vw and close>=e8 and low<=max(vw,e8)*1.006 and vol_ok: return 'READY - SNIPER PULLBACK CONFIRMED',f'5-min close above VWAP/EMA8 near {rp(close)}',['5-min pullback held','VWAP/EMA8 reclaimed','volume confirmed']
        if close>max(e8,e21,vw) and close>=high*.995 and vol_ok: return 'READY - SNIPER BREAKOUT CONFIRMED',f'5-min breakout close near {rp(close)}',['5-min breakout confirmed','volume expansion']
        return 'WAIT - WATCH FOR 5-MIN CLOSE ABOVE VWAP/EMA8',f'Trigger above {rp(max(vw,e8))}',['waiting on bullish sniper candle']
    if close<=vw and close<=e8 and high>=min(vw,e8)*.994 and vol_ok: return 'READY - SNIPER PUTBACK CONFIRMED',f'5-min close below VWAP/EMA8 near {rp(close)}',['5-min retest rejected','VWAP/EMA8 lost','volume confirmed']
    if close<min(e8,e21,vw) and close<=low*1.005 and vol_ok: return 'READY - SNIPER BREAKDOWN CONFIRMED',f'5-min breakdown close near {rp(close)}',['5-min breakdown confirmed','volume expansion']
    return 'WAIT - WATCH FOR 5-MIN CLOSE BELOW VWAP/EMA8',f'Trigger below {rp(min(vw,e8))}',['waiting on bearish sniper candle']

def grade(score): return 'A+' if score>=85 else 'A' if score>=75 else 'B+'

def score_swing(m):
    d=trend(m)
    if not d: return 0,None,['trend not clean']
    s=55; r=['clean trend']
    if d=='CALL':
        if m.ema21*.985<=m.price<=m.ema21*1.035: s+=15; r.append('near EMA21 pullback')
        if 45<=m.rsi<=65: s+=10; r.append('RSI reset')
        if m.price>m.ema8: s+=5; r.append('above EMA8')
    else:
        if m.ema21*.965<=m.price<=m.ema21*1.015: s+=15; r.append('bearish EMA21 retest')
        if 35<=m.rsi<=55: s+=10; r.append('RSI bearish reset')
        if m.price<m.ema8: s+=5; r.append('below EMA8')
    if m.rel_volume>=1.2: s+=10; r.append('relative volume confirmed')
    if no_chase(m,d): s+=5; r.append('not extended')
    return min(s,100),d,r

def score_leap(m):
    if not (m.price>m.ema50>m.ema200): return 0,None,['not a LEAP uptrend']
    s=70; r=['long-term uptrend']
    if m.price<=m.ema50*1.10: s+=10; r.append('not extended from EMA50')
    if 45<=m.rsi<=68: s+=8; r.append('RSI acceptable')
    if m.rel_volume>=1.0: s+=5; r.append('participation normal/strong')
    return min(s,100),'CALL',r

def score_0dte(m,bars):
    if m.ticker not in ZERO_DTE_TICKERS or len(bars)<6: return 0,None,['0DTE not active or insufficient bars']
    orbars=bars[:3]; hi=max(f(b.get('h')) for b in orbars); lo=min(f(b.get('l')) for b in orbars); close=f(bars[-1].get('c'))
    closes=[f(b.get('c')) for b in bars]; e8=ema(closes,8); e21=ema(closes,min(21,len(closes))); vw=m.vwap or vwap_from_bars(bars) or e21
    if close>hi and close>vw and e8>=e21: return 88,'CALL',['opening range breakout','VWAP support','EMA8/21 aligned']
    if close<lo and close<vw and e8<=e21: return 88,'PUT',['opening range breakdown','VWAP rejection','EMA8/21 aligned']
    return 0,None,['no 0DTE trigger']

def mid(c):
    q=c.get('last_quote') or {}; bid=q.get('bid'); ask=q.get('ask')
    if bid is not None and ask is not None and f(ask)>0: return (f(bid)+f(ask))/2
    t=c.get('last_trade') or {}; return f(t.get('price')) if t.get('price') is not None else None

def liq(c,midprice,strategy):
    q=c.get('last_quote') or {}; bid=f(q.get('bid')); ask=f(q.get('ask'))
    sp=((ask-bid)/midprice) if ask>0 and bid>0 and midprice>0 else None
    vol=c.get('day',{}).get('volume'); oi=c.get('open_interest')
    vi=int(vol) if vol is not None else None; oi_i=int(oi) if oi is not None else None
    max_sp=.18 if strategy=='0DTE' else .25
    ok=(sp is None or sp<=max_sp) and (oi_i is None or oi_i>=(100 if strategy=='LEAP' else 250)) and (vi is None or vi>=(1 if strategy=='LEAP' else 10))
    return ok,(round(sp,3) if sp is not None else None),vi,oi_i,('liquidity ok' if ok else f'liquidity warning: spread={sp}, vol={vi}, oi={oi_i}')

def choose_option(c,ticker,direction,strategy,price):
    if strategy=='0DTE': min_d,max_d,stop=0,1,.45
    elif strategy=='LEAP': min_d,max_d,stop=120,365,.30
    else: min_d,max_d,stop=7,30,.35
    chain=c.options(ticker,direction,min_d,max_d,price)
    candidates=[]
    for opt in chain:
        d=opt.get('details') or {}; strike=f(d.get('strike_price')); m=mid(opt)
        if not strike or not m: continue
        ok,sp,vi,oi,note=liq(opt,m,strategy)
        penalty=abs(strike-price)/max(price,1)+(0 if ok else .25)
        candidates.append((penalty,opt,m,ok,sp,vi,oi,note))
    if not candidates: return None
    candidates.sort(key=lambda x:x[0]); _,opt,m,ok,sp,vi,oi,note=candidates[0]
    d=opt.get('details') or {}; exp=d.get('expiration_date') or ''; strike=f(d.get('strike_price'))
    try: dte=max(0,(datetime.fromisoformat(exp).date()-now_et().date()).days)
    except Exception: dte=max_d
    risk=m*100*stop; contracts=max(1,int(MAX_RISK_PER_TRADE//risk)) if risk>0 else 1
    return OptionPick(d.get('ticker') or f'{ticker} {strike}{direction[0]}',exp,strike,direction,dte,rp(m),stop,rp(risk),contracts,sp,vi,oi,ok,note)

def smart_exit_engine(strategy, direction, metrics=None, status=""):
    """Adaptive exit rules based on momentum, volume, and setup type."""
    rel_volume = getattr(metrics, "rel_volume", 1.0) if metrics else 1.0
    rsi = getattr(metrics, "rsi", 50.0) if metrics else 50.0
    price = getattr(metrics, "price", 0.0) if metrics else 0.0
    ema8 = getattr(metrics, "ema8", 0.0) if metrics else 0.0
    strong_momentum = (rel_volume >= 1.5 and ((direction == "CALL" and rsi >= 58 and price >= ema8) or (direction == "PUT" and rsi <= 42 and price <= ema8)))
    if strategy == "0DTE":
        target2 = "+80% to +100% option gain - only if trend acceleration stays clean" if strong_momentum else "+45% to +55% option gain - lock most gains"
        runner = "Runner trails 5-min EMA8/VWAP; exit on first strong reversal candle" if strong_momentum else "No runner unless price holds VWAP/EMA8 after Target 2"
        return {
            "stop_loss":"Adaptive stop: early failure -10% to -15%; hard stop option -25% to -30% OR failed 5-min VWAP/EMA8 hold",
            "targets":["Fast Profit: +20% option within 30-60 min - trim/protect immediately","Target 1: +25% to +30% option - protect capital",f"Target 2: {target2}","Hard exit: 3:30 PM ET"],
            "target_1":"+25% to +30% option gain - trim/protect",
            "target_2":target2,
            "runner_rule":runner,
            "time_stop":"No follow-through after 2-3 five-minute candles = exit/reduce; hard flat by 3:30 PM ET",
            "profit_protection":"If +20% hits quickly, trim/protect and move stop near breakeven; never let a green 0DTE winner turn red",
            "exit_plan":"Adaptive 0DTE exit: take fast money, cut failed entries early, only hold runners during clean momentum.",
            "exit_checklist":["Fast profit: +20% in 30-60 min = trim/protect","Early failure: no follow-through in 2-3 candles = exit -5% to -10% if possible","Technical failure: two rejections at VWAP/EMA8 = exit","Hard stop: option -25% to -30%","Target 2 expands only when volume and trend remain strong","Flat by 3:30 PM ET"]
        }
    if strategy == "LEAP":
        target2 = "+90% to +120% option gain - trend expansion target" if strong_momentum else "+60% to +75% option gain - lock majority"
        runner = "Trail runner under EMA21 while strong; switch to EMA50 on deeper long-term hold" if strong_momentum else "Runner only while daily trend holds EMA21/EMA50"
        return {
            "stop_loss":"Adaptive stop: early thesis failure -10% to -15%; hard stop option -30% OR stock loses EMA200 / long-term thesis breaks",
            "targets":["Fast Profit: +20% option if achieved quickly - protect/trim, especially if market is choppy","Target 1: +35% option - protect capital",f"Target 2: {target2}","Runner: long-term hold only if daily trend remains intact"],
            "target_1":"+35% option gain - protect capital / reduce risk",
            "target_2":target2,
            "runner_rule":runner,
            "time_stop":"If thesis does not improve within 2-3 weeks, reassess or exit; if entry fails within 2-3 daily candles, reduce early",
            "profit_protection":"At +35%, protect principal or move stop to breakeven; at fast +20%, consider trimming if the move is news/gap driven",
            "exit_plan":"Adaptive LEAP exit: protect principal early, expand targets only when trend/volume confirm, cut failed thesis before full stop.",
            "exit_checklist":["Fast profit: +20% quickly = trim/protect if move is extended","Early failure: 2-3 daily candles fail to hold EMA21/entry zone = reduce/exit early","Technical failure: two clear EMA21/EMA50 rejections = exit/reassess","Hard stop: option -30% or stock loses EMA200","Target 2 expands to +90%-120% only in strong momentum","Runner requires intact daily/weekly trend"]
        }
    target2 = "+80% to +120% option gain - strong trend target" if strong_momentum else "+60% to +70% option gain - lock majority"
    runner = "Trail under EMA8 while strong; widen to EMA21 only after Target 2" if strong_momentum else "Runner only while daily trend holds EMA21"
    return {
        "stop_loss":"Adaptive stop: early failure -10% to -15%; hard stop option -30% to -35% OR daily close loses EMA21/EMA50 support",
        "targets":["Fast Profit: +20% option within 30-60 min - trim/protect 25%-50%","Target 1: +35% option - protect capital",f"Target 2: {target2}","Runner: trail only if trend keeps confirming"],
        "target_1":"+35% option gain - trim/protect and move stop near breakeven",
        "target_2":target2,
        "runner_rule":runner,
        "time_stop":"If trade does not move in 2-3 candles/sessions, exit or reduce before full stop",
        "profit_protection":"If +20% hits quickly, trim/protect; at +35%, move stop near breakeven; never let winner turn red",
        "exit_plan":"Adaptive swing exit: take fast profits when offered, cut no-follow-through entries early, expand targets only in strong momentum.",
        "exit_checklist":["Fast profit: +20% in 30-60 min = trim/protect","No follow-through: 2-3 candles/sessions without progress = exit/reduce","Failure exit: two EMA21 rejections = exit early -10% to -15% if possible","Hard stop: option -30% to -35%","Target 2 expands only with strong volume/trend","Runner trails EMA8/EMA21 depending on strength"]
    }

def make_idea(c,m,bars,strategy):
    if strategy=='0DTE': score,d,reasons=score_0dte(m,bars); trader='0DTE'; name='SPY/QQQ opening range sniper'
    elif strategy=='LEAP': score,d,reasons=score_leap(m); trader='LEAP'; name='Long-term trend pullback'
    else: score,d,reasons=score_swing(m); trader='SWING'; name='Pullback / momentum continuation'
    if not d or score<85: return None
    status,trigger,sn=sniper(m,bars,d,strategy)
    opt=choose_option(c,m.ticker,d,strategy,m.price)
    if opt and not opt.liquidity_ok and status.startswith('READY'): status='WAIT - OPTION LIQUIDITY WARNING'
    low=m.ema21*.995 if d=='CALL' else m.ema21*.985; high=m.ema21*1.015 if d=='CALL' else m.ema21*1.005
    exit_rules=smart_exit_engine(strategy, d, m, status)
    targets=exit_rules['targets']; stop=exit_rules['stop_loss']; exitp=exit_rules['exit_plan']
    notes=reasons+sn+([opt.liquidity_note] if opt else ['option unavailable'])
    return Idea(m.ticker,grade(score),score,trader,name,d,status,trigger,f'Daily pullback zone near EMA21: {rp(m.ema21)}',f'{rp(min(low,high))} - {rp(max(low,high))}',exitp,stop,targets,opt.contract if opt else f'{m.ticker} {d} contract unavailable',opt.estimated_entry if opt else None,opt.dte if opt else None,opt.max_contracts if opt else 0,rp(opt.risk_per_contract*opt.max_contracts) if opt else 0,rp(m.price),rp(m.rsi),round(m.rel_volume,2),notes,exit_rules['target_1'],exit_rules['target_2'],exit_rules['runner_rule'],exit_rules['time_stop'],exit_rules['profit_protection'],exit_rules['exit_checklist'])

def classify_reentry(idea,m,bars):
    if idea.status.startswith('READY') or not execution_window(idea.trader_type) or len(bars)<12: return idea
    closes=[f(b.get('c')) for b in bars]; close=closes[-1]; e8=ema(closes,8); vw=m.vwap or vwap_from_bars(bars) or e8
    if idea.direction=='CALL' and close>=max(vw,e8) and no_chase(m,'CALL',.045): idea.status='RE-ENTRY READY'; idea.sniper_trigger=f'Re-entry: 5-min reclaim above VWAP/EMA8 near {rp(close)}'; idea.notes.append('re-entry confirmed')
    if idea.direction=='PUT' and close<=min(vw,e8) and no_chase(m,'PUT',.045): idea.status='RE-ENTRY READY'; idea.sniper_trigger=f'Re-entry: 5-min rejection below VWAP/EMA8 near {rp(close)}'; idea.notes.append('re-entry confirmed')
    return idea

def load_cache():
    try: return set(json.load(open(ALERT_CACHE_FILE)))
    except Exception: return set()
def save_cache(c): json.dump(sorted(c),open(ALERT_CACHE_FILE,'w'))
def alert_key(i): return f'{today_key()}:{i.ticker}:{i.trader_type}:{i.direction}:{i.status}:{i.option_contract}'
def send_telegram(txt):7:09 PM 4/28/2026
    if not SEND_TELEGRAM or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    r=requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',json={'chat_id':TELEGRAM_CHAT_ID,'text':txt},timeout=10)
    log('Telegram alert sent' if r.status_code<400 else f'Telegram failed HTTP {r.status_code}: {r.text[:120]}')
def send_alerts(ideas):
    ready={'READY - SNIPER PULLBACK CONFIRMED','READY - SNIPER BREAKOUT CONFIRMED','READY - SNIPER PUTBACK CONFIRMED','READY - SNIPER BREAKDOWN CONFIRMED','RE-ENTRY READY'}
    cache=load_cache(); changed=False
    for i in ideas:
        if i.grade!='A+' or i.status not in ready: continue
        k=alert_key(i)
        if k in cache: continue
        send_telegram(f'🔥 APEX A+ {i.trader_type} ALERT\nTicker: {i.ticker}\nDirection: {i.direction}\nStatus: {i.status}\nTrigger: {i.sniper_trigger}\nEntry Range: {i.entry_range}\nOption: {i.option_contract}\nEst Entry: {i.estimated_option_entry}\nContracts: {i.max_contracts}\nRisk: {i.max_risk}\nStop: {i.stop_loss}\nTargets: {", ".join(i.targets)}')
        cache.add(k); changed=True
    if changed: save_cache(cache)

def push_github(payload):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        log('GitHub dashboard push not configured.'); return
    api=f'https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_DASHBOARD_PATH}'
    h={'Authorization':f'Bearer {GITHUB_TOKEN}','Accept':'application/vnd.github+json'}
    try:
        old=requests.get(api,headers=h,params={'ref':GITHUB_BRANCH},timeout=12); sha=old.json().get('sha') if old.status_code==200 else None
        body={'message':f"Update dashboard {payload.get('updated_at')}",'content':base64.b64encode(json.dumps(payload,indent=2).encode()).decode(),'branch':GITHUB_BRANCH}
        if sha: body['sha']=sha
        r=requests.put(api,headers=h,json=body,timeout=15)
        log(f'Dashboard pushed to GitHub: {GITHUB_REPO}/{GITHUB_DASHBOARD_PATH}' if r.status_code in (200,201) else f'GitHub push failed HTTP {r.status_code}: {r.text[:200]}')
    except Exception as e: log(f'GitHub push error: {e}')

def run_scan():
    log('Apex Engine v2.2 starting — Adaptive Exit Engine active, Polygon-only, Benzinga disabled.')
    log(f'Session: {session_name()} | Account size: {ACCOUNT_SIZE} | Max risk/trade: {MAX_RISK_PER_TRADE}')
    c=Polygon(POLYGON_API_KEY); ideas=[]
    for t in TICKERS:
        log(f'Scanning {t}...'); m,bars=build_metrics(c,t)
        if not m: continue
        order=['0DTE','SWING','LEAP'] if t in ZERO_DTE_TICKERS else ['SWING','LEAP']
        best=None
        for strat in order:
            idea=make_idea(c,m,bars,strat)
            if idea: idea=classify_reentry(idea,m,bars); best=idea if not best or idea.score>best.score else best
        if best:
            ideas.append(best); log(f'{best.grade} {best.ticker} {best.trader_type} {best.direction} {best.status} score={best.score} option={best.option_contract}')
    ideas.sort(key=lambda x:(x.status.startswith('READY') or x.status=='RE-ENTRY READY',x.score),reverse=True)
    payload={'updated_at':datetime.now(timezone.utc).isoformat(),'mode':'POLYGON_ONLY_BENZINGA_DISABLED_V2_1_SMART_EXIT','session':session_name(),'account_size':ACCOUNT_SIZE,'max_risk_per_trade':MAX_RISK_PER_TRADE,'ideas':[asdict(i) for i in ideas]}
    json.dump(payload,open(DASHBOARD_FILE,'w'),indent=2); push_github(payload); send_alerts(ideas)
    log(f'Scan complete. Qualified ideas: {len(ideas)}')

if __name__=='__main__':
    run_scan()
