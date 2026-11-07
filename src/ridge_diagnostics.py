"""Conditional paired block bootstrap and concentration; no future guarantee."""
import argparse,csv,hashlib,json,math,random
from pathlib import Path

def compound(returns):return 100*math.expm1(sum(math.log1p(v) for v in returns))
def quantile(values,p):
    a=sorted(values);x=(len(a)-1)*p;i=int(x);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(x-i)
def paired_bootstrap(candidate,control,block=5,replications=1000,seed=20261107):
    n=len(candidate)
    if n!=len(control) or not 1<=block<=n or type(replications) is not int or replications<100:raise ValueError('invalid paired block sample')
    if any(not math.isfinite(v) or v<=-1 for v in candidate+control):raise ValueError('invalid returns')
    delta=[math.log1p(a)-math.log1p(b) for a,b in zip(candidate,control)];rng=random.Random(seed);samples=[]
    for _ in range(replications):
        ids=[]
        while len(ids)<n:
            start=rng.randrange(n-block+1);ids.extend(range(start,start+block))
        samples.append(100*math.expm1(sum(delta[i] for i in ids[:n])))
    return dict(block=block,replications=replications,relative_wealth_advantage_pct=100*math.expm1(sum(delta)),
         relative_wealth_interval95_pct=[quantile(samples,.025),quantile(samples,.975)],
         resampled_nonpositive_frequency=sum(v<=0 for v in samples)/replications,
         limitation='Conditional resampling of studied day returns, not future loss probability; no full search correction.')

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--block',type=int,default=5)
    parser.add_argument('--replications',type=int,default=1000);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    try:
        if args.output.exists():raise ValueError('output exists; select a new path')
        returns={};dates={};hashes={}
        for policy in ('original30','fixed2','ridge'):
            path=args.run/policy/'trades.csv'
            with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
            dates[policy]=[r['day'] for r in rows];returns[policy]=[float(r['trade_return']) for r in rows];hashes[policy]=hashlib.sha256(path.read_bytes()).hexdigest()
        if not dates['ridge'] or any(dates[k]!=dates['ridge'] for k in dates):raise ValueError('policy dates must match exactly')
        if dates['ridge']!=sorted(set(dates['ridge'])):raise ValueError('dates must be unique chronological signal days')
        top=sorted(range(len(returns['ridge'])),key=lambda i:returns['ridge'][i],reverse=True)
        result=dict(period=dict(first=dates['ridge'][0],last=dates['ridge'][-1],signal_days=len(dates['ridge'])),input_sha256=hashes,
            returns={k:compound(v) for k,v in returns.items()},paired={k:paired_bootstrap(returns['ridge'],returns[k],args.block,args.replications) for k in ('original30','fixed2')},
            set_own_top_profit_days_to_zero={str(n):compound([0. if i in top[:n] else v for i,v in enumerate(returns['ridge'])]) for n in (1,3,5)},
            limitation='Top-day removal is retrospective sensitivity, not a tradable selection rule. No account/order/margin/market-depth validation.')
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print('Saved conditional diagnostics:',args.output)
    except (ValueError,OSError,KeyError) as exc:parser.error(str(exc))

if __name__=='__main__':main()
