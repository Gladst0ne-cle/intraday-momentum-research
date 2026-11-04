"""Compare all trades to a predeclared filter fixed on the earlier training period."""
import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import read_trades, evaluate_returns
from simulate import load_bars
from intraday_momentum import decide


def enrich(rows, sessions):
    """Reconstruct the selected signal using only sessions before its entry."""
    days = sorted(sessions)
    enriched = []
    for row in rows:
        day = row['date']
        if day not in sessions:
            raise ValueError('Trade date missing from bars')
        prior = [d for d in days if d < day]
        if len(prior) < 15:
            raise ValueError('Need at least 15 preceding complete sessions')
        today = sessions[day]
        first = next(iter(today.values()))['bars'][0][0]
        delta = row['entry_ms'] - first
        if delta % 1800000 or not 1 <= delta // 1800000 <= 12:
            raise ValueError('Entry is not aligned with a valid signal bar')
        index = delta // 1800000 - 1
        histories = {symbol: [sessions[d][symbol] for d in prior] for symbol in today}
        current = {symbol: session['bars'][:index+1] for symbol, session in today.items()}
        selected = decide(histories, current, index)['selected']
        if not selected or selected['inst'] != row['inst'] or selected['side'] != row['side']:
            raise ValueError('Reconstructed signal does not match trade')
        import math
        if not math.isclose(selected['leverage'], row['leverage'], rel_tol=1e-8, abs_tol=1e-10):
            raise ValueError('Reconstructed leverage does not match trade')
        enriched.append({**row, 'breach': selected['breach'], 'daily_vol': selected['daily_vol']})
    return enriched


def study(rows, train_count, feature='leverage'):
    if train_count < 3 or train_count >= len(rows):
        raise ValueError('Need at least 3 training trades and 1 test trade')
    train, test = rows[:train_count], rows[train_count:]
    if max(r['exit_ms'] for r in train) >= test[0]['entry_ms']:
        raise ValueError('Training labels overlap test period')
    if feature not in ('leverage', 'breach', 'daily_vol'):
        raise ValueError('Unsupported pre-entry feature')
    threshold = statistics.median(r[feature] for r in train)
    chosen = [r for r in test if r[feature] <= threshold]
    return {'training_trades': len(train), 'test_opportunities': len(test),
            'rule': f'pre-entry {feature} <= training median', 'training_threshold': threshold,
            'all': evaluate_returns([r['equity_return'] for r in test]),
            'filtered': evaluate_returns([r['equity_return'] for r in chosen]),
            'missed_profitable_trades': sum(r['equity_return'] > 0 for r in test if r[feature] > threshold),
            'note': 'One illustrative, predeclared rule; not evidence of predictive value. Use data available at decision time.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trades', required=True); p.add_argument('--summary', required=True)
    p.add_argument('--train-count', type=int, default=6)
    p.add_argument('--feature', choices=('leverage', 'breach', 'daily_vol'), default='leverage')
    p.add_argument('--bars', help='Original bars, required to reconstruct breach or daily volatility')
    a = p.parse_args(); rows, _ = read_trades(a.trades, a.summary)
    if a.feature != 'leverage':
        if not a.bars:
            p.error('--bars is required for breach or daily_vol')
        rows = enrich(rows, load_bars(a.bars))
    print(json.dumps(study(rows, a.train_count, a.feature), indent=2))
