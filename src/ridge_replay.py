"""Chronological Ridge exit research with shared cash accounting.

All candidates at the frozen first slot can train a later model. Only the
sigma-floor winner receives capital. Outcome prices never enter features.
"""
from __future__ import annotations
import copy,math,statistics
from collections import Counter
from datetime import datetime
import ridge_features as features
from ridge_model import fit
from intraday_momentum import decide
from versioned_replay import MINUTE,DEFAULTS,select_signal,account_path,validate_config

POLICIES=('original30','fixed2','ridge')
REGISTERED=dict(warmup_signal_days=60,refit_every_signal_days=20,embargo_signal_days=1,alpha=100.,threshold=-.0002,confirmations=2)

def validate_parent_bars(series,parent):
    for bar in parent:
        ts=bar[0];stamps=range(ts,ts+30*MINUTE,MINUTE)
        if any(t not in series for t in stamps):raise ValueError('missing minute data for parent bar')
        actual=features.aggregate([series[t] for t in stamps])
        if any(abs(a-b)>1e-6*max(1.,abs(b)) for a,b in zip(actual,bar[1:6])):
            raise ValueError('minute/30-minute OHLCV disagreement')

def context(history,bars,index):
    sigma=statistics.mean(abs(h['bars'][index][4]/h['open']-1) for h in history[-14:])
    upper=max(bars[0][1],history[-1]['close'])*(1+sigma);lower=min(bars[0][1],history[-1]['close'])*(1-sigma)
    prefix=bars[:index+1];weights=[b[5] if b[5]>0 else 1. for b in prefix]
    return dict(upper=upper,lower=lower,vwap=sum((b[2]+b[3]+b[4])/3*w for b,w in zip(prefix,weights))/sum(weights),close=prefix[-1][4])

def unit_net(item,stamp,fee=.0005,proxy=.00025):
    row=item['row'];bars={b[0]:b[1:] for b in item['minutes']};entry=bars[row['entry_ts']][0]
    if stamp not in bars:raise ValueError('missing exit/label minute')
    price=bars[stamp][0];carry=sum(-row['side']*rate*bars[ts][0] for ts,rate in item['funding'] if row['entry_ts']<ts<=stamp)
    return row['side']*(price-entry)+carry-(entry+price)*(fee+proxy)

def prepare(sessions,minutes,events,coverage,carry_zero,start=None,end=None):
    if not carry_zero and (events is None or coverage is None):raise ValueError('explicit zero carry or declared events and coverage required')
    days=sorted(sessions);symbols=set(sessions[days[0]]);history={s:[] for s in symbols};items=[]
    if len(days)<16 or any(set(sessions[d])!=symbols for d in days):raise ValueError('15 prior sessions and stable universe required')
    for day in days:
        today=sessions[day]
        if len(next(iter(history.values())))>=15 and (start is None or day>=start) and (end is None or day<=end):
            pool=[];slot=None
            for index in range(12):
                outcome=decide(history,{s:v['bars'][:index+1] for s,v in today.items()},index,None,False)
                if outcome['candidates']:pool=outcome['candidates'];slot=index;break
            if pool:
                winner,reference,floor,_=select_signal(pool,'v1.1.0')
                for row0 in pool:
                    symbol=row0['inst'];opening=today[symbol]['bars'][0][0];signal=opening+(slot+1)*30*MINUTE;entry=signal+MINUTE
                    contexts=[context(history[symbol],today[symbol]['bars'],j) for j in range(13)]
                    row={**row0,**contexts[slot], 'day':day.isoformat(),'signal_index':slot,'signal_ts':signal,'entry_ts':entry}
                    original=opening+390*MINUTE+MINUTE
                    for j in range(slot+1,12):
                        c=contexts[j];hit=c['close']<=max(c['upper'],c['vwap']) if row['side']==1 else c['close']>=min(c['lower'],c['vwap'])
                        if hit:original=opening+(j+1)*30*MINUTE+MINUTE;break
                    row['exit_ts']=original
                    if not carry_zero and not coverage[0]<=entry<original<=coverage[1]:raise ValueError('holding interval exceeds carry coverage')
                    series=minutes.get(symbol,{})
                    stamps=range(opening,opening+392*MINUTE,MINUTE)
                    if any(t not in series for t in stamps):raise ValueError('missing full current minute session: '+symbol+' '+str(day))
                    validate_parent_bars(series,today[symbol]['bars'])
                    current=[[t,*series[t]] for t in stamps]
                    five=features.five_bars(current,opening);signal5=(signal-opening)//(5*MINUTE)-1;trs=[]
                    for old in history[symbol][-14:]:
                        old_open=old['bars'][0][0];oldstamps=range(old_open,old_open+390*MINUTE,MINUTE)
                        if any(t not in series for t in oldstamps):raise ValueError('missing prior minute session: '+symbol+' '+old['day'])
                        validate_parent_bars(series,old['bars'])
                        oldfive=features.five_bars([[t,*series[t]] for t in oldstamps],old_open);trs.append(oldfive[signal5][6])
                    s0=max(statistics.median(trs),statistics.mean(b[6] for b in five[:signal5+1]))
                    if not math.isfinite(s0) or s0<=0:raise ValueError('invalid entry-time range scale')
                    item=dict(day=day.isoformat(),row=row,reference=reference,sigma_floor=floor,opening=opening,contexts=contexts,s0=s0,
                              minutes=current,funding=[] if carry_zero else events.get(symbol,[]),selected=symbol==winner['inst'])
                    states=features.build_states(item,opening+391*MINUTE)
                    terminal=unit_net(item,original);entry_price=series[entry][0]
                    labels=[(terminal-unit_net(item,s['timestamp']+MINUTE))/entry_price for s in states]
                    item.update(states=states,labels=labels);items.append(item)
        for symbol,value in today.items():history[symbol].append({**value,'day':day.isoformat()})
    if not items:raise ValueError('no eligible signal days in range')
    return items

def training_rows(items,fit_days):
    eligible_items=[it for it in items if it['day'] in fit_days];counts=Counter(it['day'] for it in eligible_items);rows=[]
    for item in eligible_items:
        active=[j for j,s in enumerate(item['states']) if s['eligible']]
        for j in active:
            rows.append(dict(day=item['day'],features=item['states'][j]['features'],label=item['labels'][j],
               weight=1/(counts[item['day']]*len(active)),label_end_ms=item['row']['exit_ts'],signal_ms=item['row']['signal_ts']))
    return rows

def rolling_predictions(items,settings=None,frozen_model=None):
    settings=dict(REGISTERED if settings is None else settings)
    if set(settings)!=set(REGISTERED) or settings!=REGISTERED:raise ValueError('only registered training/exit settings supported')
    days=sorted({it['day'] for it in items});predictions={};models=[];audit=[]
    for it in items:predictions[(it['day'],it['row']['inst'])]=None
    if frozen_model is not None:
        for it in items:
            if it['row']['signal_ts']<frozen_model.payload['prediction_not_before_ms']:raise ValueError('frozen model used before its training cutoff')
            predictions[(it['day'],it['row']['inst'])]=[frozen_model.predict(s['features']) for s in it['states']]
        return predictions,[frozen_model],dict(mode='frozen',folds=[],fallback='original30')
    for start in range(60,len(days),20):
        fit_days=days[:start-1];future=days[start:start+20];to_predict=[it for it in items if it['day'] in future]
        rows=training_rows(items,set(fit_days));first=min(it['row']['signal_ts'] for it in to_predict)
        if not rows:
            audit.append(dict(fit_until=fit_days[-1],prediction_days=future,fallback='fixed2_no_training_events'));continue
        model=fit(rows,fit_days[-1],first,100.);models.append(model)
        audit.append(dict(fit_until=fit_days[-1],embargo_day=days[start-1],prediction_days=future,model_sha256=model.digest,training_rows=len(rows)))
        for it in to_predict:predictions[(it['day'],it['row']['inst'])]=[model.predict(s['features']) for s in it['states']]
    return predictions,models,dict(mode='chronological_refit',folds=audit,warmup_signal_days=60,outer_embargo_signal_days=1,
                                  weighting='past day/candidate/eligible event',fallback='fixed2')

def exit_decision(item,policy,prediction=None,missing='fixed2'):
    if policy not in POLICIES:raise ValueError('unsupported exit policy')
    if policy!='original30':
        for j,s in enumerate(item['states']):
            if not s['eligible']:continue
            if policy=='fixed2':return s['timestamp'],'fixed2'
            if prediction is None:
                if missing=='fixed2':return s['timestamp'],'fixed2_fallback'
            elif not math.isfinite(prediction[j]):raise ValueError('nonfinite prediction')
            elif prediction[j]<-.0002:return s['timestamp'],'ridge_early_exit'
    return item['row']['exit_ts']-MINUTE,'original30'

def simulate(items,predictions,config,specs,extra_cost_bps=0,exit_delay_seconds=60,missing='fixed2'):
    config=validate_config(config)
    if not math.isfinite(extra_cost_bps) or extra_cost_bps<0 or exit_delay_seconds!=60:raise ValueError('nonnegative extra cost and registered60s delay required')
    config={**config,'execution_proxy_bps_round_trip':config['execution_proxy_bps_round_trip']+extra_cost_bps};validate_config(config)
    selected=sorted((it for it in items if it['selected']),key=lambda it:it['day']);output={}
    for policy in POLICIES:
        equity=closed_peak=minute_peak=config['initial_equity'];closed=minute=0.;records=[];curves=[]
        for it in selected:
            row=it['row'];prediction=predictions.get((it['day'],row['inst']));decision,reason=exit_decision(it,policy,prediction,missing)
            plan=dict(signal=row,reference=it['reference'],sigma_floor=it['sigma_floor'],signal_ms=row['signal_ts'],entry_ms=row['entry_ts'],
                      exit_ms=decision+MINUTE,exit_reason=reason)
            prices={b[0]:b[1] for b in it['minutes']};trade,curve=account_path(plan,equity,prices,it['funding'],config,specs[row['inst']])
            if trade is None:
                records.append(dict(day=it['day'],equity_before=equity,equity_after=equity,trade_return=0.,status='below_minimum'));continue
            before=equity;equity=trade['equity_after'];closed_peak=max(closed_peak,equity);closed=max(closed,1-equity/closed_peak)
            for point in curve:
                minute_peak=max(minute_peak,point['equity']);minute=max(minute,1-point['equity']/minute_peak)
                curves.append(dict(day=it['day'],**point))
            records.append(dict(day=it['day'],equity_before=before,equity_after=equity,trade_return=equity/before-1,**{k:v for k,v in trade.items() if k not in ('equity_before','equity_after')}))
        output[policy]=dict(initial=config['initial_equity'],equity=equity,return_pct=100*(equity/config['initial_equity']-1),
           signal_days=len(selected),max_closed_drawdown_pct=100*closed,max_minute_sampled_drawdown_pct=100*minute,
           records=records,minute_equity=curves,extra_roundtrip_cost_bps=extra_cost_bps)
    return output
