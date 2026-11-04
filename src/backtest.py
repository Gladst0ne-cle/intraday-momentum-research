"""Single-session historical replay using caller-provided 30-minute bars.

Execution is a price proxy. The caller must explicitly supply a funding/carry
function and ensure that all bars were actually available at decision time.
"""
from __future__ import annotations

import math
from intraday_momentum import decide

BAR_MS = 30 * 60 * 1000


def run_session(histories, today, session_end, carry, round_trip_fee=0.001):
    """Simulate at most one trade, or return None if there is no entry.

    ``today`` maps each symbol to 13 completed intraday bars, and ``session_end``
    maps each symbol to the timestamp and opening price at the session boundary.
    ``carry(symbol, side, entry_ms, exit_ms)`` returns a signed fraction of
    entry notional. No assumptions about missing carry are made here.
    """
    if set(histories) != set(today) or set(today) != set(session_end) or not today:
        raise ValueError('inconsistent instruments')
    if not callable(carry) or not math.isfinite(round_trip_fee) or round_trip_fee < 0:
        raise ValueError('explicit carry function and nonnegative fee required')
    timeline = None
    for symbol, bars in today.items():
        if len(bars) != 13:
            raise ValueError('a session requires 13 intraday bars')
        stamps = [bar[0] for bar in bars]
        if any(stamps[i + 1] - stamps[i] != BAR_MS for i in range(12)):
            raise ValueError('non-contiguous intraday bars')
        if timeline is None:
            timeline = stamps
        elif timeline != stamps:
            raise ValueError('instruments must share the same timeline')
        if session_end[symbol][0] != stamps[-1] + BAR_MS:
            raise ValueError('invalid session boundary')
    position = None
    pending = None
    traded = False

    def finish(exit_ms, exit_price, reason):
        if not math.isfinite(float(exit_price)) or exit_price <= 0:
            raise ValueError('invalid exit price')
        holding = float(carry(position['inst'], position['side'], position['entry_ms'], exit_ms))
        if not math.isfinite(holding):
            raise ValueError('carry must be finite')
        gross = position['side'] * (exit_price / position['entry_px'] - 1.0)
        return {**position, 'exit_ms': exit_ms, 'exit_px': exit_price, 'reason': reason,
                'gross_return': gross, 'carry_return': holding,
                'equity_return': position['leverage'] * (gross + holding - round_trip_fee)}

    for i in range(13):
        if pending:
            px = float(today[pending['inst']][i][1])
            if not math.isfinite(px) or px <= 0:
                raise ValueError('invalid proxy price')
            if pending['kind'] == 'exit':
                return finish(timeline[i], px, 'band_vwap')
            position = {**pending['signal'], 'entry_ms': timeline[i], 'entry_px': px}
            traded = True
            pending = None
        available = {symbol: bars[:i + 1] for symbol, bars in today.items()}
        decision = decide(histories, available, i, position, traded)
        if position and decision['exit_trigger'] and i < 12:
            pending = {'kind': 'exit', 'inst': position['inst']}
        elif not position and not traded and decision['selected']:
            pending = {'kind': 'entry', 'inst': decision['selected']['inst'], 'signal': decision['selected']}
    if position:
        exit_ms, exit_price = session_end[position['inst']]
        return finish(exit_ms, float(exit_price), 'session_close')
    return None


def account(trades):
    """Compound sequential trade returns; drawdown ignores intratrade moves."""
    wealth = peak = 1.0
    drawdown = 0.0
    wins = 0
    for trade in trades:
        ret = float(trade['equity_return'])
        if not math.isfinite(ret) or ret <= -1:
            raise ValueError('invalid return or insolvency; model does not simulate liquidation')
        wealth *= 1 + ret
        peak = max(peak, wealth)
        drawdown = min(drawdown, wealth / peak - 1)
        wins += ret > 0
    return {'trades': len(trades), 'wealth': wealth, 'return': wealth - 1,
            'max_drawdown_after_completed_trades': drawdown,
            'win_rate': wins / len(trades) if trades else None}
