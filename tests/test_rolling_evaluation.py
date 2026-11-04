import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import rolling_evaluation as rolling
import simulate


class RollingTests(unittest.TestCase):
    def test_complete_partition_matches_full_period(self):
        sessions = simulate.synthetic_sessions()
        carry = lambda *_: 0.0
        _, whole = simulate.simulate(sessions, carry)
        report = rolling.evaluate(sessions, carry, fold_days=5)
        self.assertEqual([f['evaluated_days'] for f in report['folds']], [5, 5, 1])
        self.assertTrue(report['folds'][-1]['partial_final_fold'])
        self.assertEqual(sum(f['trades'] for f in report['folds']), whole['trades'])
        self.assertAlmostEqual(math.prod(1 + f['return'] for f in report['folds']), whole['wealth'])
        self.assertTrue(all(f['prior_sessions'] >= 15 for f in report['folds']))

    def test_invalid_fold_size(self):
        with self.assertRaises(ValueError):
            rolling.evaluate(simulate.synthetic_sessions(), lambda *_: 0.0, fold_days=0)

    def test_cli_output_and_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'rolling.json'
            cmd = [sys.executable, str(ROOT / 'src' / 'rolling_evaluation.py'), '--demo', '--output', str(output)]
            env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
            first = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result['data_type'], 'synthetic_demo')
            self.assertEqual(len(result['folds']), 3)
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
