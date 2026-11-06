import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from replay_cli import demo_inputs, load_minutes, load_specs
from versioned_replay import DEFAULTS, MINUTE, account_path, allocate, replay, select_signal, validate_config


def candidate(symbol, breach, sigma, vol=.02):
    return dict(inst=symbol, side=1, breach=breach, sigma=sigma, daily_vol=vol)


SPEC = dict(quantity_step=.01, minimum_quantity=.01, unit_value=1)


class VersionedTests(unittest.TestCase):
    def test_floor_changes_rank_without_reading_outcomes(self):
        pool = [candidate('A', .02, .10), candidate('B', .015, .01), candidate('C', .001, .05)]
        a, ref, floor, target = select_signal(pool, 'v1.0.0')
        self.assertEqual(a['inst'], 'A')
        b, ref, floor, target = select_signal(pool, 'v2.0.0')
        self.assertEqual(b['inst'], 'B')
        self.assertEqual(ref['inst'], 'A')
        self.assertEqual(floor, .05)
        for row in pool:
            row.update(future_return=100 if row['inst'] == 'C' else -100)
        self.assertEqual(select_signal(pool, 'v2.0.0')[0]['inst'], 'B')

    def test_ties_and_invalid_features(self):
        pool = [candidate('Z', .02, .03), candidate('A', .02, .03)]
        self.assertEqual(select_signal(pool, 'v2.0.0')[0]['inst'], 'A')
        pool[0]['sigma'] = 0
        with self.assertRaises(ValueError):
            select_signal(pool, 'v2.0.0')

    def test_reference_risk_and_collateral_budget(self):
        selected, reference = candidate('B', .01, .01, .06), candidate('A', .02, .03, .03)
        sized = allocate(1000, 100, selected, reference, DEFAULTS, SPEC)
        self.assertLessEqual(sized['exposure'], .04/.06)
        self.assertLessEqual(sized['volatility_risk_proxy'], .04)
        self.assertEqual(sized['margin_leverage'], 1.34)
        # Four-times exposure must leave entry cost headroom.
        low_vol = candidate('A', .01, .01, .001)
        sized = allocate(1000, 100, low_vol, low_vol, DEFAULTS, SPEC)
        self.assertLess(sized['exposure'], 4)
        self.assertLessEqual(sized['exposure']/4 + sized['exposure']*.00075, 1)

    def test_quantity_step_and_non_unit_contract(self):
        row = candidate('A', .02, .03)
        spec = dict(quantity_step=.1, minimum_quantity=.1, unit_value=10)
        sized = allocate(1000, 100, row, row, DEFAULTS, spec)
        self.assertAlmostEqual(sized['quantity'], 1.9)
        self.assertEqual(sized['unit_value'], 10)
        self.assertIsNone(allocate(1, 100, row, row, DEFAULTS, spec))

    def test_exit_notional_fees_and_settlement_price_carry(self):
        row = candidate('A', .02, .03)
        plan = dict(signal=row, reference=row, sigma_floor=.03, signal_ms=0,
                    entry_ms=MINUTE, exit_ms=3*MINUTE, exit_reason='band_vwap')
        prices = {MINUTE: 100., 2*MINUTE: 80., 3*MINUTE: 110.}
        trade, curve = account_path(plan, 1000, prices, [(MINUTE, .9), (2*MINUTE, .001)], DEFAULTS, SPEC)
        q = trade['quantity']
        self.assertAlmostEqual(trade['fees'], q*(100+110)*.0005)
        self.assertAlmostEqual(trade['funding'], -q*80*.001)
        self.assertAlmostEqual(trade['execution_cost_proxy'], q*210*.00025)
        self.assertAlmostEqual(curve[-1]['equity'], trade['equity_after'])
        self.assertLess(curve[1]['equity'], 1000)
        self.assertGreater(trade['equity_after'], 1000)
        prices.pop(2*MINUTE)
        with self.assertRaisesRegex(ValueError, 'missing or invalid minute'):
            account_path(plan, 1000, prices, [], DEFAULTS, SPEC)

    def test_short_carry_sign_and_duplicate_settlement(self):
        row = candidate('A', .02, .03)
        row['side'] = -1
        plan = dict(signal=row, reference=row, sigma_floor=.03, signal_ms=0,
                    entry_ms=MINUTE, exit_ms=2*MINUTE, exit_reason='session_close')
        prices = {MINUTE: 100, 2*MINUTE: 90}
        trade, _ = account_path(plan, 1000, prices, [(2*MINUTE, .001)], DEFAULTS, SPEC)
        self.assertGreater(trade['funding'], 0)
        with self.assertRaises(ValueError):
            account_path(plan, 1000, prices, [(2*MINUTE, .001)]*2, DEFAULTS, SPEC)

    def test_missing_carry_or_coverage_fails(self):
        sessions, minutes, specs, _ = demo_inputs()
        with self.assertRaises(ValueError):
            replay(sessions, minutes, specs, DEFAULTS)
        with self.assertRaisesRegex(ValueError, 'coverage'):
            replay(sessions, minutes, specs, DEFAULTS, {}, (0, MINUTE))

    def test_minute_risk_and_compounding(self):
        sessions, minutes, specs, _ = demo_inputs()
        result = replay(sessions, minutes, specs, DEFAULTS, carry_zero=True)
        trades = result['trades']
        self.assertGreater(len(trades), 0)
        for previous, current in zip(trades, trades[1:]):
            self.assertEqual(previous['equity_after'], current['equity_before'])
        summary = result['summary']
        self.assertGreaterEqual(summary['max_minute_sampled_closeout_drawdown_percent'],
                                summary['max_closed_drawdown_percent']-1e-9)
        self.assertTrue(all(t['entry_ms'] == t['signal_ms']+MINUTE for t in trades))
        self.assertTrue(all(t['entry_ms'] < t['exit_ms'] for t in trades))
        self.assertEqual(len({t['date'] for t in trades}), len(trades))

    def test_finite_config_and_registered_delay(self):
        for key, value in [('initial_equity', float('nan')), ('delay_minutes', 0),
                           ('version', 'v99'), ('fee_bps_per_side', -1)]:
            with self.assertRaises(ValueError):
                validate_config({**DEFAULTS, key: value})

    def test_cli_export_reload_and_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = str(ROOT/'scripts/run_replay.py')
            example, output = root/'example', root/'demo'
            command = [sys.executable, script, '--demo', '--compare', '--export-example', str(example), '--output', str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            again = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            real = subprocess.run([sys.executable, script, '--bars', str(example/'bars30.csv'),
                                   '--minutes', str(example/'minutes.csv'), '--specs', str(example/'specs.csv'),
                                   '--carry-zero', '--compare', '--output', str(root/'reload')], capture_output=True, text=True)
            self.assertEqual(real.returncode, 0, real.stderr)
            for version in ('v1.0.0', 'v2.0.0'):
                a = json.loads((output/version/'summary.json').read_text())
                b = json.loads((root/'reload'/version/'summary.json').read_text())
                self.assertAlmostEqual(a['final_equity'], b['final_equity'])
            self.assertEqual(set(load_specs(example/'specs.csv')), {'AAA', 'BBB', 'CCC'})
            self.assertTrue(load_minutes(example/'minutes.csv'))


if __name__ == '__main__':
    unittest.main()
