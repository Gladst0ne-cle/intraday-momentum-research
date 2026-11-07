"""Venue-neutral Ridge training/replay CLI; no network calls."""
import argparse,csv,hashlib,json,math
from pathlib import Path
from datetime import date
from replay_cli import rows_from_csv,load_specs,load_events,write_csv
from simulate import load_bars,synthetic_sessions,save_synthetic_bars,timestamp_ms,finite_float
from versioned_replay import DEFAULTS,MINUTE
from ridge_model import RidgeModel
from ridge_replay import REGISTERED,prepare,rolling_predictions,simulate

def load_ohlcv(path):
    series={}
    for row in rows_from_csv(path,['symbol','timestamp_ms','open','high','low','close','volume']):
        symbol=row['symbol'].strip();ts=timestamp_ms(row['timestamp_ms']);b=[finite_float(row[k],k) for k in ('open','high','low','close','volume')]
        o,h,lo,c,v=b
        if not symbol or ts%MINUTE or min(o,h,lo,c)<=0 or v<0 or h<max(o,lo,c) or lo>min(o,h,c):raise ValueError('invalid minute OHLCV')
        target=series.setdefault(symbol,{})
        if ts in target:raise ValueError('duplicate minute')
        target[ts]=b
    if not series:raise ValueError('empty minutes')
    return series

def demo_inputs():
    sessions=synthetic_sessions(100);minutes={};rows=[]
    for _,symbols in sorted(sessions.items()):
        for symbol,session in symbols.items():
            target=minutes.setdefault(symbol,{})
            for index,(ts,o,h,lo,c,v) in enumerate(list(session['bars'])):
                generated=[]
                for j in range(30):
                    # Deliberate fictional excursions exercise confirmation
                    # events and model training; never performance evidence.
                    def at(k):return (o+(c-o)*k/30)*(1+.018*math.sin(2*math.pi*k/30))
                    opening=at(j);close=at(j+1)
                    b=[opening,max(opening,close)*1.0001,min(opening,close)*.9999,close,v/30]
                    target[ts+j*MINUTE]=b
                    generated.append(b)
                    rows.append(dict(symbol=symbol,timestamp_ms=ts+j*MINUTE,**dict(zip(('open','high','low','close','volume'),b))))
                # The30m and minute inputs describe the same fictional path.
                session['bars'][index]=(ts,generated[0][0],max(b[1] for b in generated),min(b[2] for b in generated),generated[-1][3],v)
            ts,px=session['session_end']
            for j in range(2):
                target[ts+j*MINUTE]=[px,px,px,px,0.]
                rows.append(dict(symbol=symbol,timestamp_ms=ts+j*MINUTE,open=px,high=px,low=px,close=px,volume=0.))
    specs={s:dict(quantity_step=.01,minimum_quantity=.01,unit_value=1.) for s in minutes}
    return sessions,minutes,specs,rows

def main(argv=None):
    parser=argparse.ArgumentParser(description='v1.2.0 offline Ridge exit study; fictional demo or your own CSV inputs.')
    source=parser.add_mutually_exclusive_group(required=True);source.add_argument('--demo',action='store_true');source.add_argument('--bars',type=Path)
    parser.add_argument('--minutes',type=Path);parser.add_argument('--specs',type=Path);parser.add_argument('--config',type=Path)
    carry=parser.add_mutually_exclusive_group();carry.add_argument('--carry-zero',action='store_true');carry.add_argument('--carry-file',type=Path)
    parser.add_argument('--carry-coverage-start');parser.add_argument('--carry-coverage-end');parser.add_argument('--frozen-model',type=Path)
    parser.add_argument('--initial-equity',type=float);parser.add_argument('--start',type=date.fromisoformat);parser.add_argument('--end',type=date.fromisoformat)
    parser.add_argument('--cost-grid',action='store_true',help='Keep decisions fixed; add0/2/5/10/20/40bp round-trip execution cost')
    parser.add_argument('--export-example',type=Path);parser.add_argument('--output',type=Path,default=Path('output/ridge'));args=parser.parse_args(argv)
    try:
        if args.start and args.end and args.start>args.end:raise ValueError('start after end')
        if args.output.exists():raise ValueError('output already exists; select a new directory')
        if args.export_example and args.export_example.exists():raise ValueError('example directory already exists')
        config=json.loads(args.config.read_text(encoding='utf-8')) if args.config else dict(version='v1.2.0',training=REGISTERED,accounting={**DEFAULTS,'initial_equity':300.})
        if set(config)!= {'version','training','accounting'} or config['version']!='v1.2.0' or config['training']!=REGISTERED:raise ValueError('unsupported Ridge config')
        accounting=config['accounting']
        if args.initial_equity is not None:accounting={**accounting,'initial_equity':args.initial_equity}
        if args.demo:
            if any((args.minutes,args.specs,args.carry_file,args.carry_coverage_start,args.carry_coverage_end,args.frozen_model)):raise ValueError('demo cannot combine external data or a historical fitted model')
            sessions,minutes,specs,example=demo_inputs();events=coverage=None;zero=True
        else:
            if not args.minutes or not args.specs or args.export_example:raise ValueError('bars needs minute OHLCV and specs; example export is demo only')
            sessions,minutes,specs=load_bars(args.bars),load_ohlcv(args.minutes),load_specs(args.specs)
            if set(minutes)!=set(specs):raise ValueError('minute and specification universe differ')
            if args.carry_zero:
                if args.carry_coverage_start or args.carry_coverage_end:raise ValueError('zero carry cannot have coverage arguments')
                events=coverage=None;zero=True
            elif args.carry_file and args.carry_coverage_start and args.carry_coverage_end:
                events,coverage=load_events(args.carry_file,args.carry_coverage_start,args.carry_coverage_end);zero=False
                if set(events)-set(specs):raise ValueError('carry contains unknown symbols')
            else:raise ValueError('declare zero carry or supply carry file and coverage')
        model=RidgeModel.load(args.frozen_model) if args.frozen_model else None
        items=prepare(sessions,minutes,events,coverage,zero,args.start,args.end)
        if set(specs)!=set(next(iter(sessions.values()))):raise ValueError('specifications do not match bar universe')
        predictions,models,audit=rolling_predictions(items,config['training'],model)
        missing='original30' if model else 'fixed2'
        results=simulate(items,predictions,accounting,specs,missing=missing)
        stresses={}
        if args.cost_grid:
            for bp in (0,2,5,10,20,40):
                m=simulate(items,predictions,accounting,specs,extra_cost_bps=bp,missing=missing)
                stresses[str(bp)]={k:{f:v for f,v in value.items() if f not in ('records','minute_equity')} for k,value in m.items()}
        inputs={role:hashlib.sha256(p.read_bytes()).hexdigest() for role,p in [('bars',args.bars),('minutes',args.minutes),('specs',args.specs),('carry',args.carry_file),('config',args.config),('frozen_model',args.frozen_model)] if p}
        summary=dict(release='v1.2.0',data_type='fictional_demo' if args.demo else 'user_supplied',input_sha256=inputs,
          first_signal_day=min(it['day'] for it in items),last_signal_day=max(it['day'] for it in items),
          signal_days=len({it['day'] for it in items}),candidate_paths=len(items),model_count=len(models),training=audit,
          policies={k:{f:v for f,v in value.items() if f not in ('records','minute_equity')} for k,value in results.items()},
          cost_grid=stresses,limitations=['No actual fills or profitability guarantee.','Fictional demo cannot reproduce historical evidence.',
           'Full result includes fixed2 warmup if using rolling training.','Feature net values retain frozen15bp baseline; cost scenarios do not retrain models.',
           'Minute proxy prices omit order-book matching, intraminute marks, margin and liquidation.'])
        # Compute everything before creating output, so missing data leaves no
        # seemingly successful partial result.
        args.output.mkdir(parents=True);(args.output/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        (args.output/'training.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf-8')
        modeldir=args.output/'models';modeldir.mkdir()
        for index,fitted in enumerate(models):fitted.save(modeldir/f'fold-{index+1}.json')
        for policy,m in results.items():
            directory=args.output/policy;directory.mkdir();write_csv(directory/'trades.csv',m['records']);write_csv(directory/'minute_equity.csv',m['minute_equity'])
        if args.export_example:
            args.export_example.mkdir(parents=True);save_synthetic_bars(args.export_example/'bars30.csv',sessions)
            write_csv(args.export_example/'minutes.csv',example);write_csv(args.export_example/'specs.csv',[dict(symbol=s,**v) for s,v in specs.items()])
        for key,m in results.items():print(f"{key} | {summary['data_type']} | days={m['signal_days']} | return={m['return_pct']:.4f}% | minute DD={m['max_minute_sampled_drawdown_pct']:.4f}%")
        print(f"models={len(models)} | output={args.output}")
    except (ValueError,OSError,KeyError,TypeError) as exc:parser.error(str(exc))

if __name__=='__main__':main()
