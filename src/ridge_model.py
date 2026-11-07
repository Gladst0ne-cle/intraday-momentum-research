"""Small deterministic Ridge regression with an unpenalized intercept.

Standard-library Cholesky solver; no optional ML dependency is required.
Training data must contain only labels completed before prediction begins.
"""
import json,math,statistics
from pathlib import Path
from ridge_features import FEATURES,canonical,sha

def solve_spd(a,b):
    n=len(b);lower=[[0.]*n for _ in range(n)]
    for i in range(n):
        for j in range(i+1):
            value=a[i][j]-sum(lower[i][k]*lower[j][k] for k in range(j))
            if i==j:
                if value<=0 or not math.isfinite(value):raise ValueError('non-positive Ridge system')
                lower[i][j]=math.sqrt(value)
            else:lower[i][j]=value/lower[j][j]
    y=[0.]*n
    for i in range(n):y[i]=(b[i]-sum(lower[i][k]*y[k] for k in range(i)))/lower[i][i]
    x=[0.]*n
    for i in reversed(range(n)):x[i]=(y[i]-sum(lower[k][i]*x[k] for k in range(i+1,n)))/lower[i][i]
    return x

class RidgeModel:
    def __init__(self,payload):
        if payload.get('schema')!='offline-ridge-v1' or payload.get('features')!=list(FEATURES):raise ValueError('unsupported feature schema')
        for name in ('mean','scale','coef'):
            if len(payload[name])!=21 or not all(type(v) in (float,int) and math.isfinite(v) for v in payload[name]):raise ValueError('invalid model vector')
        if min(payload['scale'])<=0 or not math.isfinite(payload['intercept']):raise ValueError('invalid model values')
        self.payload=payload;self.digest=sha(payload)
    def predict(self,features):
        if len(features)!=21 or not all(type(v) in (int,float) and math.isfinite(v) for v in features):raise ValueError('invalid features')
        p=self.payload
        return p['intercept']+sum(c*max(-8.,min(8.,(x-m)/s)) for x,m,s,c in zip(features,p['mean'],p['scale'],p['coef']))
    def save(self,path):Path(path).write_text(json.dumps(self.payload,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    @classmethod
    def load(cls,path,expected_sha256=None):
        obj=cls(json.loads(Path(path).read_text(encoding='utf-8')))
        if expected_sha256 is not None and obj.digest!=expected_sha256:raise ValueError('model checksum mismatch')
        return obj

def fit(rows,fit_until,predict_from,alpha=100.):
    """rows: features, label, weight, day, label_end_ms, signal_ms.

    predict_from is an actual timestamp (not a date guessed at midnight).
    Whole-day outer separation is additionally enforced by the replay caller.
    """
    if not rows or not math.isfinite(alpha) or alpha<=0:raise ValueError('training rows and positive regularization required')
    if any(r['day']>fit_until or r['label_end_ms']>=predict_from for r in rows):raise ValueError('training label crosses prediction boundary')
    if any(len(r['features'])!=21 or not all(math.isfinite(v) for v in r['features']) or not math.isfinite(r['label']) or not math.isfinite(r['weight']) or r['weight']<=0 for r in rows):raise ValueError('invalid training data')
    n=len(rows);mean=[statistics.mean(r['features'][j] for r in rows) for j in range(21)]
    scale=[max(1e-8,math.sqrt(sum((r['features'][j]-mean[j])**2 for r in rows)/n)) for j in range(21)]
    x=[[max(-8.,min(8.,(v-m)/s)) for v,m,s in zip(r['features'],mean,scale)] for r in rows]
    y=[max(-.05,min(.05,r['label'])) for r in rows];weights=[r['weight'] for r in rows];total=sum(weights)
    xm=[sum(w*z[j] for w,z in zip(weights,x))/total for j in range(21)];ym=sum(w*t for w,t in zip(weights,y))/total
    a=[[0.]*21 for _ in range(21)];b=[0.]*21
    for z,target,w in zip(x,y,weights):
        delta=[v-m for v,m in zip(z,xm)]
        for j in range(21):
            b[j]+=w*delta[j]*(target-ym)
            for k in range(j+1):a[j][k]+=w*delta[j]*delta[k]
    for j in range(21):
        a[j][j]+=alpha
        for k in range(j):a[k][j]=a[j][k]
    coef=solve_spd(a,b);intercept=ym-sum(c*m for c,m in zip(coef,xm))
    return RidgeModel(dict(schema='offline-ridge-v1',features=list(FEATURES),mean=mean,scale=scale,coef=coef,
              intercept=intercept,alpha=alpha,fit_until=fit_until,prediction_not_before_ms=predict_from,
              training_event_rows=n,weighting='day / candidate path / eligible event',classification='offline_research_only'))
