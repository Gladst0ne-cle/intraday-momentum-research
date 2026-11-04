"""Causal, deliberately simple return prediction and rolling residual intervals."""
import argparse
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import read_trades, evaluate_returns


def predict(train, row):
    """OLS on the pre-entry leverage feature; constant fallback for zero variance."""
    xs = [x['leverage'] for x in train]
    ys = [x['equity_return'] for x in train]
    xm, ym = statistics.mean(xs), statistics.mean(ys)
    denom = sum((x - xm) ** 2 for x in xs)
    slope = sum((x-xm)*(y-ym) for x,y in zip(xs,ys)) / denom if denom > 1e-12 else 0.0
    return ym + slope * (row['leverage'] - xm)


def eligible(rows, index):
    """Only labels completed strictly before this signal's entry may train it."""
    return [r for r in rows[:index] if r['exit_ms'] < rows[index]['entry_ms']]


def mse(predictions, actual):
    return statistics.mean((a-b)**2 for a,b in zip(predictions, actual)) if actual else None


def fixed_split(rows, train_count):
    if train_count < 3 or train_count >= len(rows):
        raise ValueError('Need at least 3 training trades and at least 1 test trade')
    train, test = rows[:train_count], rows[train_count:]
    if max(r['exit_ms'] for r in train) >= test[0]['entry_ms']:
        raise ValueError('Training labels overlap the test period')
    actual = [r['equity_return'] for r in test]
    zero = [0.0] * len(test)
    mean = [statistics.mean(r['equity_return'] for r in train)] * len(test)
    linear = [predict(train, r) for r in test]
    selected = [r['equity_return'] for r,p in zip(test, linear) if p > 0]
    return {'training_trades': len(train), 'test_trades': len(test),
            'mse': {'zero': mse(zero, actual), 'training_mean': mse(mean, actual), 'linear': mse(linear, actual)},
            'all_trades': evaluate_returns(actual), 'linear_positive_only': evaluate_returns(selected),
            'note': 'Single fixed split; the signal filter is exploratory and not a validated trading rule.'}


def rolling(rows, initial, coverage=.8):
    if initial < 3 or initial >= len(rows) or not 0 < coverage < 1:
        raise ValueError('Need at least 3 initial trades, a later trade, and coverage in (0,1)')
    past_errors, records = [], []
    for i in range(initial, len(rows)):
        train = eligible(rows, i)
        if len(train) < initial:
            continue
        prediction = predict(train, rows[i])
        # Past out-of-sample predictions become available only after their labels end.
        usable = sorted(abs(err) for end, err in past_errors if end < rows[i]['entry_ms'])
        radius = usable[min(len(usable)-1, math.ceil((len(usable)+1)*coverage)-1)] if usable else None
        actual = rows[i]['equity_return']
        records.append({'date': str(rows[i]['date']), 'prediction': prediction, 'actual': actual,
                        'lower': prediction-radius if radius is not None else None,
                        'upper': prediction+radius if radius is not None else None,
                        'calibration_count': len(usable)})
        past_errors.append((rows[i]['exit_ms'], actual-prediction))
    tested = [r for r in records if r['lower'] is not None]
    return {'records': records, 'interval_coverage_observed': sum(r['lower'] <= r['actual'] <= r['upper'] for r in tested)/len(tested) if tested else None,
            'note': 'Expanding past-only predictions and empirical absolute residual intervals; no coverage guarantee. Inspect sample size.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trades', required=True); p.add_argument('--summary', required=True)
    p.add_argument('--train-count', type=int, default=6)
    p.add_argument('--mode', choices=('fixed', 'rolling'), default='fixed')
    a = p.parse_args(); rows, _ = read_trades(a.trades, a.summary)
    print(json.dumps(fixed_split(rows, a.train_count) if a.mode == 'fixed' else rolling(rows, a.train_count), indent=2))
