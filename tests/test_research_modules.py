import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


prediction = module('research/models/prediction.py', 'prediction')
filter_study = module('research/signals/filter_study.py', 'filter_study')
risk = module('research/risk/scenarios.py', 'scenarios')
quality = module('research/data_quality/check_bars.py', 'check_bars')


def sample():
    return [{'date': f'2026-01-{i+1:02d}', 'entry_ms': i*100+10, 'exit_ms': i*100+50,
             'leverage': 1 + i/10, 'equity_return': (i-4)/100, 'gross_return': (i-4)/100,
             'carry_return': 0, 'side': 1, 'inst': 'AAA'} for i in range(10)]


class ResearchTests(unittest.TestCase):
    def test_future_returns_do_not_change_earlier_predictions_or_threshold(self):
        rows = sample()
        changed = deepcopy(rows)
        changed[-1]['equity_return'] = 0.9
        first, second = prediction.rolling(rows, 4), prediction.rolling(changed, 4)
        self.assertEqual(first['records'][:-1], second['records'][:-1])
        self.assertEqual(first['records'][-1]['prediction'], second['records'][-1]['prediction'])
        self.assertEqual(filter_study.study(rows, 4)['training_threshold'], filter_study.study(changed, 4)['training_threshold'])

    def test_split_rejects_overlapping_labels(self):
        rows = sample()
        rows[3]['exit_ms'] = rows[4]['entry_ms']
        with self.assertRaises(ValueError): prediction.fixed_split(rows, 4)
        with self.assertRaises(ValueError): filter_study.study(rows, 4)

    def test_sizing_and_gap_stop(self):
        rows = [{'date': 'day', 'entry_ms': 100, 'exit_ms': 3600100, 'inst': 'A', 'side': 1,
                 'leverage': 1, 'gross_return': -.12, 'carry_return': 0, 'equity_return': -.12}]
        sessions = {'day': {'A': {'bars': [(100, 100, 101, 99, 100, 1),
                    (1800100, 90, 92, 89, 90, 1)], 'session_end': (3600100, 88)}}}
        result = risk.run(rows, 0, 1, 4, .05, sessions)
        self.assertEqual(result['stops_triggered'], 1)
        self.assertAlmostEqual(result['result']['wealth'], .9)
        rows[0]['carry_return'] = .01
        with self.assertRaises(ValueError): risk.run(rows, 0, 1, 4, .05, sessions)

    def test_fresh_demo_commands_and_calendar(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); out = p/'run'; bars = p/'bars.csv'
            commands = [
                ['src/simulate.py', '--demo', '--save-demo-bars', str(bars), '--output', str(out)],
                ['research/data_quality/check_bars.py', '--bars', str(bars)],
                ['research/risk/scenarios.py', '--trades', str(out/'trades.csv'), '--summary', str(out/'summary.json'), '--bars', str(bars), '--stop', '.05'],
                ['research/signals/filter_study.py', '--trades', str(out/'trades.csv'), '--summary', str(out/'summary.json')],
                ['research/signals/filter_study.py', '--trades', str(out/'trades.csv'), '--summary', str(out/'summary.json'), '--bars', str(bars), '--feature', 'breach'],
                ['research/models/prediction.py', '--trades', str(out/'trades.csv'), '--summary', str(out/'summary.json'), '--mode', 'fixed'],
                ['research/models/prediction.py', '--trades', str(out/'trades.csv'), '--summary', str(out/'summary.json'), '--mode', 'rolling'],
            ]
            for args in commands:
                result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, encoding='utf-8',
                                        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
                self.assertEqual(result.returncode, 0, result.stderr)
                json.loads(result.stdout)
            calendar = p/'calendar.csv'; calendar.write_text('date\n2026-01-05\n', encoding='utf-8')
            report = quality.check(bars, calendar)
            self.assertTrue(report['calendar_checked'])
            self.assertTrue(report['unexpected_sessions'])


if __name__ == '__main__': unittest.main()
