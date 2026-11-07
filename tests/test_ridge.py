import copy,json,math,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from ridge_cli import demo_inputs,load_ohlcv
from ridge_replay import prepare,rolling_predictions,simulate,training_rows,exit_decision,REGISTERED
from ridge_features import build_states,original_exit,MINUTE
from ridge_model import fit,RidgeModel,solve_spd
from ridge_diagnostics import paired_bootstrap,compound
from versioned_replay import DEFAULTS,select_signal

class ModelTests(unittest.TestCase):
    def rows(self):
        return [dict(features=[i/10]*21,label=.001*i,weight=1.,day='2026-01-01',signal_ms=10,label_end_ms=100) for i in range(20)]
    def test_solver(self):
        x=solve_spd([[4.,1.],[1.,3.]],[1.,2.]);self.assertAlmostEqual(x[0],1/11);self.assertAlmostEqual(x[1],7/11)
    def test_regularization_and_constant_features(self):
        rows=self.rows()
        for row in rows:row['features']=[1.]*21
        m=fit(rows,'2026-01-01',200);self.assertAlmostEqual(m.predict([1.]*21),.0095)
    def test_training_label_boundary_rejected(self):
        with self.assertRaises(ValueError):fit(self.rows(),'2026-01-01',100)
    def test_training_day_boundary_rejected(self):
        with self.assertRaises(ValueError):fit(self.rows(),'2025-12-31',200)
    def test_invalid_model_and_feature_values(self):
        m=fit(self.rows(),'2026-01-01',200)
        with self.assertRaises(ValueError):m.predict([math.nan]*21)
        payload=copy.deepcopy(m.payload);payload['scale'][0]=0
        with self.assertRaises(ValueError):RidgeModel(payload)
    def test_model_roundtrip_and_checksum(self):
        m=fit(self.rows(),'2026-01-01',200)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model.json';m.save(path);self.assertEqual(m.predict([.5]*21),RidgeModel.load(path,m.digest).predict([.5]*21))
            with self.assertRaises(ValueError):RidgeModel.load(path,'0'*64)
    def test_identical_paired_returns_zero_interval(self):
        r=[.01,-.02,.03,.005]*10;m=paired_bootstrap(r,r,5,100)
        self.assertEqual(m['relative_wealth_interval95_pct'],[0,0]);self.assertAlmostEqual(compound([.1,-.1]),-1)
    def test_version_alias_preserves_selection(self):
        pool=[dict(inst='A',side=1,breach=.01,sigma=.02,daily_vol=.03)]
        self.assertEqual(select_signal(pool,'v1.1.0'),select_signal(pool,'v2.0.0'))

class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sessions,cls.minutes,cls.specs,_=demo_inputs();cls.items=prepare(cls.sessions,cls.minutes,None,None,True)
        cls.pred,cls.models,cls.audit=rolling_predictions(cls.items)
    def test_demo_actually_trains(self):
        self.assertGreaterEqual(len(self.models),1);self.assertGreaterEqual(len({it['day'] for it in self.items}),80)
    def test_whole_day_embargo(self):
        for fold in self.audit['folds']:
            self.assertLess(fold['fit_until'],fold['embargo_day']);self.assertLess(fold['embargo_day'],fold['prediction_days'][0])
    def test_future_minutes_and_contexts_cannot_change_prefix(self):
        item=next(it for it in self.items if len(it['states'])>=3);cutoff=item['states'][1]['timestamp']
        expected=build_states(item,cutoff);modified=copy.deepcopy(item)
        for bar in modified['minutes']:
            if bar[0]>=cutoff:bar[1:5]=[v*3 for v in bar[1:5]]
        for j,c in enumerate(modified['contexts']):
            if modified['opening']+(j+1)*30*MINUTE>cutoff:c.update(close=1,upper=1,lower=1,vwap=1)
        self.assertEqual(expected,build_states(modified,cutoff))
    def test_original_exit_priority(self):
        for item in self.items[:10]:
            original=original_exit(item,item['opening']+391*MINUTE)
            self.assertEqual(original+MINUTE,item['row']['exit_ts'])
            self.assertTrue(all(s['timestamp']<original for s in item['states']))
    def test_future_exit_label_not_read_as_feature(self):
        item=self.items[0];changed=copy.deepcopy(item);changed['row']['exit_ts']+=99999999
        self.assertEqual(build_states(item,item['opening']+391*MINUTE),build_states(changed,item['opening']+391*MINUTE))
    def test_day_path_event_weighting(self):
        day=self.items[0]['day'];rows=training_rows(self.items,{day})
        self.assertLessEqual(sum(r['weight'] for r in rows),1+1e-12)
        self.assertTrue(all(r['day']==day for r in rows))
    def test_missing_minute_fails_without_substitute_trade(self):
        data=copy.deepcopy(self.minutes);item=self.items[0];data[item['row']['inst']].pop(item['row']['entry_ts'])
        with self.assertRaises(ValueError):prepare(self.sessions,data,None,None,True)
    def test_no_implicit_zero_carry(self):
        with self.assertRaises(ValueError):prepare(self.sessions,self.minutes,None,None,False)
    def test_minute_parent_disagreement_rejected(self):
        data=copy.deepcopy(self.minutes);item=self.items[0];stamp=item['opening'];bar=data[item['row']['inst']][stamp]
        bar[1]*=1.5
        with self.assertRaisesRegex(ValueError,'OHLCV disagreement'):prepare(self.sessions,data,None,None,True)
    def test_fixed_parameters_not_silently_tuned(self):
        with self.assertRaises(ValueError):rolling_predictions(self.items,{**REGISTERED,'alpha':1.})
    def test_frozen_model_cannot_predict_its_training_past(self):
        with self.assertRaises(ValueError):rolling_predictions(self.items,frozen_model=self.models[-1])
    def test_same_entry_same_budget_compounding(self):
        output=simulate(self.items,self.pred,{**DEFAULTS,'initial_equity':300},self.specs)
        for m in output.values():
            self.assertAlmostEqual(m['equity'],m['records'][-1]['equity_after'])
            self.assertGreaterEqual(m['max_minute_sampled_drawdown_pct'],m['max_closed_drawdown_pct']-1e-8)
            for record in m['records']:
                if record.get('status')=='below_minimum':continue
                self.assertEqual(record['entry_ms'],record['signal_ms']+MINUTE)
                self.assertLessEqual(record['exposure'],record['reference_exposure']+1e-10)
    def test_cost_grid_is_not_a_retraining(self):
        original=copy.deepcopy(self.pred);simulate(self.items,self.pred,{**DEFAULTS,'initial_equity':300},self.specs,extra_cost_bps=20)
        self.assertEqual(original,self.pred)
    def test_candidate_exit_does_not_exceed_original_deadline(self):
        for item in self.items:
            d,_=exit_decision(item,'ridge',self.pred[(item['day'],item['row']['inst'])])
            self.assertLessEqual(d+MINUTE,item['row']['exit_ts'])

class CLITests(unittest.TestCase):
    def test_demo_export_reload_and_sensitivity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);example=root/'example';out=root/'run';script=str(ROOT/'scripts/run_ridge.py')
            first=subprocess.run([sys.executable,script,'--demo','--export-example',str(example),'--output',str(out)],capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            second=subprocess.run([sys.executable,script,'--bars',str(example/'bars30.csv'),'--minutes',str(example/'minutes.csv'),
                 '--specs',str(example/'specs.csv'),'--carry-zero','--output',str(root/'reload')],capture_output=True,text=True)
            self.assertEqual(second.returncode,0,second.stderr)
            a=json.loads((out/'summary.json').read_text());b=json.loads((root/'reload/summary.json').read_text())
            for policy in ('original30','fixed2','ridge'):self.assertAlmostEqual(a['policies'][policy]['equity'],b['policies'][policy]['equity'],places=8)
            check=subprocess.run([sys.executable,str(ROOT/'scripts/check_ridge.py'),'--run',str(out),'--replications','100','--output',str(root/'diagnostics.json')],capture_output=True,text=True)
            self.assertEqual(check.returncode,0,check.stderr)
            again=subprocess.run([sys.executable,script,'--demo','--output',str(out)],capture_output=True,text=True)
            self.assertNotEqual(again.returncode,0)

if __name__=='__main__':unittest.main()
