"""Shared, venue-neutral inputs for research scripts."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from research_analysis import load_trades, summary


def read_trades(trades, summary_file):
    meta = json.loads(Path(summary_file).read_text(encoding='utf-8'))
    fee = float(meta['round_trip_fee_bps'])
    return load_trades(trades, fee), fee


def evaluate_returns(values):
    """Compound fixed equity returns; never invent a result after insolvency."""
    if any(r <= -1 for r in values):
        return {'trades': len(values), 'wealth': None, 'insolvency': True}
    wealth = peak = 1.0
    drawdown = 0.0
    for r in values:
        wealth *= 1 + r
        peak = max(peak, wealth)
        drawdown = max(drawdown, 1 - wealth / peak)
    return {'trades': len(values), 'wealth': wealth, 'max_closed_trade_drawdown': drawdown,
            'win_rate': sum(r > 0 for r in values) / len(values) if values else None,
            'insolvency': False}
