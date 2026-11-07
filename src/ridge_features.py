"""Causal21 exit features. Offline and venue neutral; no network or orders."""
from __future__ import annotations
import hashlib,json,math,statistics
from datetime import datetime,time
from pathlib import Path
from zoneinfo import ZoneInfo

MINUTE=60000
ET=ZoneInfo('America/New_York')
FEATURES=('holding','since_peak','net','peak','giveback','vwap_distance','return5','range_scale',
 'boundary_distance','daily_vol','sigma','breach','next_clock_check','line_distance','second_close_change',
 'vwap_slope','violation_streak','relative_session_volume','directional_close_location','relative_last_volume','warning_age')

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def opening_ms(day):
    return int(datetime.combine(datetime.fromisoformat(day).date(),time(9,30),ET).timestamp()*1000)

def research_entry_minute(target_ms,fill_ms):
    """Map a real fill onto the trained entry: the minute open one minute after the decision.

    A fill timestamp inside that minute is the same research entry. A fill in another
    minute is a different trade and must not be relabeled with this candle.
    """
    if type(target_ms) is not int or target_ms%MINUTE or type(fill_ms) is not int or fill_ms<=0:
        raise ValueError('invalid entry schedule')
    if not target_ms<=fill_ms<target_ms+MINUTE:
        raise ValueError('fill is outside the research entry minute')
    return target_ms

def aggregate(group):
    active=[b for b in group if b[4]>0] or group
    return (active[0][0],max(b[1] for b in active),min(b[2] for b in active),active[-1][3],sum(b[4] for b in group))

def five_bars(minutes,opening):
    by={b[0]:tuple(b[1:6]) for b in minutes};result=[];previous=None
    for index in range(78):
        ts=opening+index*5*MINUTE;stamps=range(ts,ts+5*MINUTE,MINUTE)
        if any(t not in by for t in stamps):break
        o,h,lo,c,v=aggregate([by[t] for t in stamps]);ref=o if previous is None else previous
        result.append([ts,o,h,lo,c,v,max(h-lo,abs(h-ref),abs(lo-ref))]);previous=c
    return result

def finite(value):return type(value) in (int,float) and math.isfinite(value)
def validate_minutes(minutes,opening,asof):
    seen=set()
    for b in minutes:
        if b[0]+MINUTE>asof:continue
        if len(b)!=6 or type(b[0]) is not int or b[0]%MINUTE or b[0] in seen:raise ValueError('duplicate or invalid minute')
        if not all(finite(x) for x in b[1:]) or min(b[1:5])<=0 or b[5]<0 or b[2]<max(b[1:5]) or b[3]>min(b[1:5]):raise ValueError('invalid OHLCV')
        seen.add(b[0])
    usable=sorted((b for b in minutes if opening<=b[0] and b[0]+MINUTE<=asof),key=lambda b:b[0])
    if usable and [b[0] for b in usable]!=list(range(opening,usable[-1][0]+MINUTE,MINUTE)):raise ValueError('missing minute prefix')
    return usable

def original_exit(item,asof):
    """Derive from completed contexts only. Never accepts a future exit label."""
    opening=item['opening'];row=item['row'];side=row['side']
    for j,context in enumerate(item['contexts']):
        boundary=opening+(j+1)*30*MINUTE
        if j<=row['signal_index'] or boundary>asof:continue
        hit=context['close']<=max(context['upper'],context['vwap']) if side==1 else context['close']>=min(context['lower'],context['vwap'])
        if hit or j==12:return boundary
    return opening+390*MINUTE if asof>=opening+390*MINUTE else None

def build_states(item,asof_ms):
    """Port of frozen21 causal features, rebuilt from a minute prefix only."""
    row=item['row'];opening=item['opening'];side=row['side'];s0=item['s0']
    if type(side) is not int or side not in (-1,1) or not finite(s0) or s0<=0:raise ValueError('invalid frozen position')
    for name in ('sigma','breach','daily_vol','upper','lower'):
        if not finite(row[name]) or row[name]<=0:raise ValueError('invalid signal feature')
    minutes=validate_minutes(item['minutes'],opening,asof_ms);bars={b[0]:b[1:6] for b in minutes}
    entry_ts=row.get('entry_ts')
    if type(entry_ts) is not int or entry_ts%MINUTE:raise ValueError('entry timestamp must be the research minute open')
    if entry_ts not in bars:raise ValueError('entry minute open unavailable')
    entry=bars[entry_ts][0]
    supplied=row.get('entry_price')
    if supplied is not None and not math.isclose(float(supplied),entry,rel_tol=0,abs_tol=1e-9*max(entry,1)):
        raise ValueError('feature entry price must be the research minute open')
    if not finite(entry) or entry<=0:raise ValueError('invalid entry price')
    five=five_bars(minutes,opening);stop=original_exit(item,asof_ms)
    flows={}
    for ts,rate in item['funding']:
        if not finite(rate) or type(ts) is not int or ts%MINUTE or ts in flows:raise ValueError('invalid funding event')
        if row['entry_ts']<ts<=asof_ms and ts in bars:flows[ts]=-side*rate*bars[ts][0]
    volume=weighted=fund=0.;peak=-math.inf;peak_time=row['entry_ts'];vwaps={};states=[];streak=0;warning=None
    for ts,b in sorted(bars.items()):
        o,h,lo,c,v=b;volume+=v;weighted+=(h+lo+c)/3*v
        if volume>0:vwaps[ts+MINUTE]=weighted/volume
        if ts>=row['entry_ts']:
            fund+=flows.get(ts,0.);net=side*(c-entry)+fund-(entry+c)*.00075
            if net>peak:peak,peak_time=net,ts+MINUTE
        decision=ts+MINUTE
        if (decision-opening)%(5*MINUTE) or decision-5*MINUTE<row['entry_ts']:continue
        if stop is not None and decision>=stop:break
        if volume<=0 or not math.isfinite(peak):raise ValueError('minute VWAP or held-price prefix unavailable')
        slot=(decision-opening)//(5*MINUTE)-1;bar=five[slot];prev=five[slot-1];c=bar[4];vwap=weighted/volume
        ci=(decision-opening)//(30*MINUTE)-1
        if not 0<=ci<len(item['contexts']):raise ValueError('missing last completed30 context')
        ctx=item['contexts'][ci];line=max(ctx['upper'],ctx['vwap']) if side==1 else min(ctx['lower'],ctx['vwap'])
        holding=(decision-row['entry_ts'])/MINUTE;since=max(0.,(decision-peak_time)/MINUTE);boundary=row['upper'] if side==1 else row['lower']
        hit=side*(c-line)<=0;streak=streak+1 if hit else 0
        if hit and warning is None:warning=decision
        if not hit:warning=None
        prior_vwap=vwaps.get(decision-5*MINUTE)
        if prior_vwap is None:raise ValueError('previous VWAP unavailable')
        mean_volume=statistics.mean(b[5] for b in five[:slot]) if slot else bar[5]
        x=[holding/390,since/60,net/entry,peak/entry,(peak-net)/entry,side*(c-vwap)/entry,side*(c/prev[4]-1),bar[6]/s0,
           side*(c-boundary)/s0,row['daily_vol'],row['sigma'],row['breach'],(30-((decision-opening)//MINUTE)%30)/30,
           side*(c-line)/s0,side*(c-prev[4])/s0,side*(vwap-prior_vwap)/s0,streak/6,bar[5]/max(1.,mean_volume),
           side*(2*c-bar[2]-bar[3])/max(bar[2]-bar[3],1e-8,1e-4*s0),bar[5]/(prev[5]+1.),0. if warning is None else (decision-warning)/(60*MINUTE)]
        if not all(finite(v) for v in x):raise ValueError('nonfinite features')
        states.append(dict(timestamp=decision,features=x,eligible=streak>=2,streak=streak))
    return states
