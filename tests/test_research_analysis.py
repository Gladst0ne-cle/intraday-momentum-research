import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import research_analysis as research


def trade(day, entry, ret, leverage=1.0):
    return {'date': day, 'inst': 'AAA', 'side': 1, 'entry_ms': entry,
            'exit_ms': entry + 1800000, 'leverage': leverage,
            'gross_return': ret / leverage + .001, 'carry_return': 0.0,
            'equity_return': ret, 'reason': 'session_close'}


class AnalysisTests(unittest.TestCase):
    def test_cost_concentration_and_time_segments(self):
        rows = [trade(date(2026, 1, 2), 1000000, .1),
                trade(date(2026, 1, 3), 10000000, -.1),
                trade(date(2026, 1, 4), 20000000, .2)]
        result = research.analyze(rows, [0, 20])
        self.assertAlmostEqual(result['base']['wealth'], 1.1 * .9 * 1.2)
        self.assertAlmostEqual(result['extra_cost_scenarios_bps']['20']['wealth'], 1.098 * .898 * 1.198)
        self.assertEqual(result['concentration']['largest_winning_trade_count'], 2)
        self.assertAlmostEqual(result['concentration']['remove_largest_winners_after_the_fact']['wealth'], .9)
        self.assertEqual(result['chronological_halves']['first']['statistics']['trades'], 1)
        self.assertEqual(result['chronological_halves']['second']['statistics']['trades'], 2)
        self.assertEqual(result['holding_minutes']['median'], 30)

    def test_insolvency_does_not_fake_equity(self):
        rows = [trade(date(2026, 1, 2), 1000000, -.99, leverage=4)]
        result = research.summary(rows, extra_bps=30)
        self.assertTrue(result['insolvency_in_scenario'])
        self.assertIsNone(result['wealth'])

    def test_input_formula_and_chronological_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'trades.csv'
            rows = [trade(date(2026, 1, 2), 1000000, .1), trade(date(2026, 1, 3), 10000000, -.1)]
            with path.open('w', encoding='utf-8', newline='') as out:
                writer = csv.DictWriter(out, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual(len(research.load_trades(path, 10)), 2)
            with self.assertRaisesRegex(ValueError, '不一致'):
                research.load_trades(path, 20)
            with path.open('a', encoding='utf-8', newline='') as out:
                csv.DictWriter(out, fieldnames=list(rows[0])).writerow(rows[1])
            with self.assertRaisesRegex(ValueError, '顺序'):
                research.load_trades(path, 10)

    def test_end_to_end_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'simulation'
            report = Path(folder) / 'research.json'
            env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
            sim = subprocess.run([sys.executable, str(ROOT / 'src' / 'simulate.py'), '--demo', '--output', str(output)],
                                 capture_output=True, text=True, encoding='utf-8', env=env)
            self.assertEqual(sim.returncode, 0, sim.stderr)
            cmd = [sys.executable, str(ROOT / 'src' / 'research_analysis.py'), '--trades', str(output / 'trades.csv'),
                   '--summary', str(output / 'summary.json'), '--output', str(report)]
            run = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(result['input_context']['data_type'], 'synthetic_demo')
            self.assertEqual(result['input_context']['base_round_trip_fee_bps'], 10)
            self.assertIn('20', result['extra_cost_scenarios_bps'])
            again = subprocess.run(cmd, capture_output=True)
            self.assertNotEqual(again.returncode, 0)


if __name__ == '__main__':
    unittest.main()
