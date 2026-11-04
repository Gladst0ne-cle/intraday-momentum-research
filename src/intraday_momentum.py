"""Venue-neutral 30-minute intraday noise-band decision rule.

Input bars are caller-supplied tuples (timestamp, open, high, low, close, volume).
This module places no orders and does not load any market data.
"""
from __future__ import annotations

import math
import statistics

LOOKBACK = 14
VOL_TARGET = 0.04
LEVERAGE_CAP = 4.0


def daily_volatility(history: list[dict]) -> float | None:
    """Sample standard deviation of 14 close-to-close returns."""
    if len(history) < LOOKBACK + 1:
        return None
    closes = [float(s['close']) for s in history[-(LOOKBACK + 1):]]
    if not all(math.isfinite(x) and x > 0 for x in closes):
        raise ValueError('history closes must be finite and positive')
    value = statistics.stdev(closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)))
    return value if value > 0 else None


def decide(histories: dict, today: dict, index: int, position: dict | None = None,
           traded: bool = False) -> dict:
    """Return a signal or exit decision using only bars through ``index``.

    Each history is 15 or more complete, chronologically ordered sessions with
    ``open``, ``close`` and ``bars``. The caller must validate market calendars,
    timestamps and that inputs were available at the decision time.
    """
    if not 0 <= index < 13 or set(histories) != set(today):
        raise ValueError('inconsistent symbols or bar index')
    if position and (position.get('inst') not in today or position.get('side') not in (-1, 1)):
        raise ValueError('invalid position')
    candidates = []
    exit_trigger = False
    for ticker, bars in today.items():
        hist = histories[ticker]
        if len(bars) != index + 1:
            raise ValueError('incomplete current session')
        if len(hist) < LOOKBACK + 1:
            continue
        opening = float(bars[0][1])
        close = float(bars[-1][4])
        if not all(math.isfinite(x) and x > 0 for x in (opening, close)):
            raise ValueError('invalid prices')
        moves = [abs(float(s['bars'][index][4]) / float(s['open']) - 1) for s in hist[-LOOKBACK:]]
        if not all(math.isfinite(x) for x in moves):
            raise ValueError('invalid historical moves')
        sigma = sum(moves) / LOOKBACK
        previous_close = float(hist[-1]['close'])
        upper = max(opening, previous_close) * (1.0 + sigma)
        lower = min(opening, previous_close) * (1.0 - sigma)
        weights = [float(bar[5]) if float(bar[5]) > 0 else 1.0 for bar in bars]
        vwap = sum((bar[2] + bar[3] + bar[4]) / 3 * w for bar, w in zip(bars, weights)) / sum(weights)
        if position and position['inst'] == ticker:
            exit_trigger = ((position['side'] == 1 and close <= max(upper, vwap)) or
                            (position['side'] == -1 and close >= min(lower, vwap)))
        elif not position and not traded and index < 12:
            side = 1 if close > upper else (-1 if close < lower else 0)
            if side:
                volatility = daily_volatility(hist)
                if volatility:
                    breach = (close - upper) / close if side == 1 else (lower - close) / close
                    candidates.append({'inst': ticker, 'side': side, 'breach': breach,
                                       'sigma': sigma, 'daily_vol': volatility,
                                       'leverage': min(LEVERAGE_CAP, VOL_TARGET / volatility)})
    candidates.sort(key=lambda c: (-c['breach'], c['inst']))
    return {'candidates': candidates, 'selected': candidates[0] if candidates else None,
            'exit_trigger': exit_trigger}
