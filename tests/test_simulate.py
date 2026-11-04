import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import simulate


def save_sessions(path, sessions):
    with path.open('w', encoding='utf-8', newline='') as out:
        fields = ['symbol', 'timestamp_ms', 'open', 'high', 'low', 'close', 'volume']
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for day, symbols in sorted(sessions.items()):
            for symbol, data in sorted(symbols.items()):
                for ts, op, high, low, close, vol in data['bars']:
                    writer.writerow(dict(symbol=symbol, timestamp_ms=ts, open=op, high=high, low=low, close=close, volume=vol))
                ts, op = data['session_end']
                writer.writerow(dict(symbol=symbol, timestamp_ms=ts, open=op, high=op, low=op, close=op, volume=0))


class SimulationTests(unittest.TestCase):
    def test_demo_cli_and_repeat_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'out'
            cmd = [sys.executable, str(ROOT / 'src' / 'simulate.py'), '--demo', '--output', str(output)]
            run = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            self.assertEqual(run.returncode, 0, run.stderr)
            summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['data_type'], 'synthetic_demo')
            self.assertEqual(summary['evaluated_days'], 11)
            self.assertGreater(summary['trades'], 0)
            with (output / 'trades.csv').open(encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), summary['trades'])
            self.assertAlmostEqual(float(rows[-1]['equity_after']), summary['final_equity'])
            again = subprocess.run(cmd, capture_output=True)
            self.assertNotEqual(again.returncode, 0)

    def test_supplied_csv_matches_demo_and_bad_rows_fail(self):
        sessions = simulate.synthetic_sessions()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bars.csv'
            save_sessions(path, sessions)
            loaded = simulate.load_bars(path)
            expected = simulate.simulate(sessions, lambda *_: 0.0)
            actual = simulate.simulate(loaded, lambda *_: 0.0)
            self.assertEqual(actual, expected)
            generated = Path(folder) / 'export.csv'
            simulate.save_synthetic_bars(generated, sessions)
            self.assertEqual(simulate.load_bars(generated), sessions)
            with self.assertRaises(ValueError):
                simulate.save_synthetic_bars(generated, sessions)
            with path.open(encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
            rows.append(dict(rows[0]))
            with self.assertRaisesRegex(ValueError, '重复'):
                simulate.build_sessions(rows)
            rows.pop()
            rows.pop()
            with self.assertRaisesRegex(ValueError, '缺少完整'):
                simulate.build_sessions(rows)

    def test_carry_interval_sign_and_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'carry.csv'
            path.write_text('symbol,timestamp_ms,rate\nAAA,2000,0.001\nAAA,3000,-0.002\n', encoding='utf-8')
            carry = simulate.load_carry(path, '1000', '4000')
            self.assertAlmostEqual(carry('AAA', 1, 1000, 3000), .001)
            self.assertAlmostEqual(carry('AAA', -1, 1000, 3000), -.001)
            self.assertAlmostEqual(carry('AAA', 1, 2000, 3000), .002)
            with self.assertRaises(ValueError):
                carry('AAA', 1, 999, 3000)

    def test_external_bars_require_explicit_carry_assumption(self):
        with tempfile.TemporaryDirectory() as folder:
            bars = Path(folder) / 'bars.csv'
            save_sessions(bars, simulate.synthetic_sessions())
            output = Path(folder) / 'out'
            cmd = [sys.executable, str(ROOT / 'src' / 'simulate.py'), '--bars', str(bars), '--output', str(output)]
            run = subprocess.run(cmd, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((output / 'summary.json').exists())


if __name__ == '__main__':
    unittest.main()
