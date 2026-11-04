import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from intraday_momentum import decide, daily_volatility
from backtest import run_session, account


def session(n):
    opening = 100.0 + n * .2
    close = opening * (1.001 if n % 2 else .999)
    return {'open': opening, 'close': close,
            'bars': [(i, opening, opening * 1.002, opening * .998, close, 100) for i in range(13)]}


class StrategyTests(unittest.TestCase):
    def test_breakout_and_existing_position_exit(self):
        history = [session(i) for i in range(15)]
        bar = (0, 103.0, 107.0, 102.0, 106.0, 100)
        outcome = decide({'ABC': history}, {'ABC': [bar]}, 0)
        self.assertEqual(outcome['selected']['side'], 1)
        self.assertLessEqual(outcome['selected']['leverage'], 4)
        exit_bar = (1, 106.0, 106.0, 99.0, 100.0, 100)
        exit_result = decide({'ABC': history}, {'ABC': [bar, exit_bar]}, 1, {'inst':'ABC','side':1}, True)
        self.assertTrue(exit_result['exit_trigger'])

    def test_reject_missing_bars_and_invalid_close(self):
        history = [session(i) for i in range(15)]
        with self.assertRaises(ValueError):
            decide({'ABC': history}, {'ABC': []}, 0)
        history[-1]['close'] = math.nan
        with self.assertRaises(ValueError):
            daily_volatility(history)

    def test_next_bar_fill_and_compounding(self):
        history = [session(i) for i in range(15)]
        bars = [(i * 1800000, 103.0 if i == 0 else 106.0, 107.0, 102.0, 106.0, 100) for i in range(13)]
        trade = run_session({'ABC': history}, {'ABC': bars}, {'ABC': (13 * 1800000, 107.0)},
                            carry=lambda *args: 0.0)
        self.assertEqual(trade['entry_ms'], 1800000)
        self.assertEqual(trade['reason'], 'session_close')
        self.assertEqual(trade['exit_px'], 107.0)
        summary = account([trade])
        self.assertAlmostEqual(summary['wealth'], 1 + trade['equity_return'])
        with self.assertRaises(ValueError):
            run_session({'ABC': history}, {'ABC': bars}, {'ABC': (13 * 1800000, 107.0)}, carry=None)


if __name__ == '__main__':
    unittest.main()
