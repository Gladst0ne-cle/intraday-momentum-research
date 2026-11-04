"""Offline position sizing and bar-based stop scenarios, not an execution model."""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import read_trades, evaluate_returns
from simulate import load_bars


def run(rows, fee_bps, factor, cap, stop, sessions=None):
    if not all(math.isfinite(x) for x in (factor, cap)) or factor <= 0 or cap <= 0:
        raise ValueError('Factor and cap must be finite and positive')
    if stop is not None and (not math.isfinite(stop) or not 0 < stop < 1):
        raise ValueError('Stop must be between 0 and 1')
    if stop is not None and sessions is None:
        raise ValueError('Bars required for stop scenarios')
    outcomes, stopped = [], 0
    for r in rows:
        lev = min(r['leverage'] * factor, cap)
        gross, carry = r['gross_return'], r['carry_return']
        if stop is not None:
            if carry != 0:
                raise ValueError('Stop scenarios require zero carry: its timing cannot be reconstructed')
            session = sessions[r['date']][r['inst']]
            bars = [b for b in session['bars'] if r['entry_ms'] <= b[0] < r['exit_ms']]
            if not bars or bars[0][0] != r['entry_ms'] or len(bars)*1800000 != r['exit_ms']-r['entry_ms']:
                raise ValueError('Missing or misaligned bars during trade')
            entry = bars[0][1]
            exit_prices = {b[0]: b[1] for b in session['bars']}
            exit_prices[session['session_end'][0]] = session['session_end'][1]
            if r['exit_ms'] not in exit_prices or not math.isclose(
                r['side'] * (exit_prices[r['exit_ms']] / entry - 1), r['gross_return'],
                rel_tol=1e-8, abs_tol=1e-10
            ):
                raise ValueError('Bars do not match the recorded trade entry and exit')
            if r['side'] == 1:
                trigger = entry * (1 - stop / lev)
            else:
                trigger = entry * (1 + stop / lev)
            if trigger <= 0:
                raise ValueError('Stop price is nonpositive')
            for _, opening, high, low, _, _ in bars:
                hit = low <= trigger if r['side'] == 1 else high >= trigger
                if hit:
                    fill = min(opening, trigger) if r['side'] == 1 else max(opening, trigger)
                    gross = r['side'] * (fill / entry - 1)
                    stopped += 1
                    break
        outcomes.append(lev * (gross + carry - fee_bps / 10000))
    return {'result': evaluate_returns(outcomes), 'stops_triggered': stopped,
            'assumptions': 'Fixed price paths, no liquidation; OHLC stops use trigger price or worse bar open. No intrabar order, latency or slippage model. Zero carry required for stops.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trades', required=True); p.add_argument('--summary', required=True)
    p.add_argument('--factor', type=float, default=1); p.add_argument('--cap', type=float, default=4)
    p.add_argument('--stop', type=float, help='loss before fees as fraction of equity, e.g. 0.05')
    p.add_argument('--bars', help='same full 30-minute bars as simulation, required with --stop')
    a = p.parse_args()
    if a.stop is not None and not a.bars:
        p.error('--bars is required with --stop')
    trades, fee = read_trades(a.trades, a.summary)
    print(json.dumps(run(trades, fee, a.factor, a.cap, a.stop, load_bars(a.bars) if a.bars else None), indent=2))
