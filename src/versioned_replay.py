"""Versioned, venue-neutral offline research. No network or order submission.

Signal planning consumes completed bars only. The accounting phase is the
only phase permitted to read subsequent minute prices and carry settlements.
"""
from __future__ import annotations

import math
import statistics
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from intraday_momentum import decide

MINUTE = 60_000
VERSIONS = {'v1.0.0', 'v1.1.0', 'v2.0.0'}  # v2 is a retained legacy alias
DEFAULTS = dict(version='v1.1.0', initial_equity=10000.0,
                fee_bps_per_side=5.0, execution_proxy_bps_round_trip=5.0,
                delay_minutes=1, leverage_step=0.01)


def validate_config(config):
    if set(config) != set(DEFAULTS):
        raise ValueError('config must contain exactly: ' + ', '.join(DEFAULTS))
    if config['version'] not in VERSIONS:
        raise ValueError('unsupported strategy version')
    for key in DEFAULTS.keys() - {'version'}:
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'invalid {key}')
    if config['initial_equity'] <= 0 or not 0 < config['leverage_step'] <= 1:
        raise ValueError('positive equity and leverage step in (0, 1] required')
    if config['delay_minutes'] != 1:
        raise ValueError('registered versions require exactly one minute execution delay')
    for key in ('fee_bps_per_side', 'execution_proxy_bps_round_trip'):
        if not 0 <= config[key] < 1000:
            raise ValueError(f'{key} must be in [0, 1000)')
    return dict(config)


def select_signal(pool, version):
    """First-slot pool only; tie-break by symbol. No outcome fields are read."""
    if version not in VERSIONS or not pool:
        raise ValueError('supported version and nonempty candidate pool required')
    if len({r['inst'] for r in pool}) != len(pool):
        raise ValueError('duplicate candidate symbol')
    for row in pool:
        if row['side'] not in (-1, 1):
            raise ValueError('side must be -1 or 1')
        if not all(math.isfinite(row[k]) and row[k] > 0 for k in ('sigma', 'breach', 'daily_vol')):
            raise ValueError('positive finite candidate features required')
    reference = min(pool, key=lambda r: (-r['breach'], r['inst']))
    floor = statistics.median(r['sigma'] for r in pool)
    selected = reference if version == 'v1.0.0' else min(
        pool, key=lambda r: (-r['breach'] / max(r['sigma'], floor), r['inst']))
    reference_gross = min(4.0, .04 / reference['daily_vol'])
    target = min(reference_gross, reference_gross * reference['daily_vol'] / selected['daily_vol'])
    return dict(selected), dict(reference), floor, target


def plan_session(histories, today, version):
    """Freeze one entry and causal original-rule exit; no minute prices read.

    Each decision uses only today's prefix and earlier complete sessions.
    No late substitute after an unaffordable first signal is allowed.
    """
    selected = reference = None
    for index in range(13):
        prefix = {symbol: item['bars'][:index + 1] for symbol, item in today.items()}
        outcome = decide(histories, prefix, index, selected, selected is not None)
        boundary = next(iter(prefix.values()))[-1][0] + 30 * MINUTE
        if selected is not None:
            if index == 12 or outcome['exit_trigger']:
                return dict(signal=selected, reference=reference, sigma_floor=floor,
                            target_exposure=target, signal_ms=signal_ms,
                            entry_ms=signal_ms + MINUTE, exit_ms=boundary + MINUTE,
                            exit_reason='session_close' if index == 12 else 'band_vwap')
        elif outcome['candidates']:
            # Zero movement has no stable normalized denominator; fail explicitly.
            selected, reference, floor, target = select_signal(outcome['candidates'], version)
            signal_ms = boundary
    return None


def allocate(equity, entry_price, selected, reference, config, spec):
    """Round quantity DOWN, round margin leverage UP, reserve entry costs."""
    if not all(math.isfinite(x) and x > 0 for x in (equity, entry_price)):
        raise ValueError('positive equity and entry price required')
    vals = {k: Decimal(str(spec[k])) for k in ('quantity_step', 'minimum_quantity', 'unit_value')}
    if any(not v.is_finite() or v <= 0 for v in vals.values()):
        raise ValueError('invalid instrument specification')
    gross = min(4.0, .04 / reference['daily_vol'])
    risk = gross * reference['daily_vol']
    target = min(gross, risk / selected['daily_vol'])
    step = Decimal(str(config['leverage_step']))
    margin_leverage = max(Decimal(1), (Decimal(str(gross)) / step).to_integral_value(
        rounding=ROUND_CEILING) * step)
    entry_cost = config['fee_bps_per_side'] / 10000 + config['execution_proxy_bps_round_trip'] / 20000
    collateral_cap = float(margin_leverage / (1 + margin_leverage * Decimal(str(entry_cost))))
    scale = min(1.0, collateral_cap / target)
    price = Decimal(str(entry_price))
    quantity = (Decimal(str(equity)) * Decimal(str(target * scale)) /
                price / vals['unit_value'] / vals['quantity_step']).to_integral_value(
                    rounding=ROUND_FLOOR) * vals['quantity_step']
    if quantity < vals['minimum_quantity']:
        return None
    notional = float(quantity * vals['unit_value'] * price)
    exposure = notional / equity
    if (exposure > gross + 1e-10 or exposure * selected['daily_vol'] > risk + 1e-10
            or exposure / float(margin_leverage) + exposure * entry_cost > 1 + 1e-10):
        raise ValueError('reference or collateral budget exceeded')
    return dict(quantity=float(quantity), unit_value=float(vals['unit_value']),
                exposure=exposure, margin_leverage=float(margin_leverage),
                target_exposure=target, reference_exposure=gross,
                volatility_risk_proxy=exposure * selected['daily_vol'])


def account_path(plan, before, prices, events, config, spec):
    """Minute-open close-out proxies, including hypothetical exit costs.

    Carry uses the settlement minute's opening price as a mark-price proxy.
    Events must be complete, on minute boundaries, and within declared coverage.
    This function does not simulate liquidation, matching or partial fills.
    """
    if (plan['entry_ms'] >= plan['exit_ms'] or plan['entry_ms'] % MINUTE
            or plan['exit_ms'] % MINUTE):
        raise ValueError('entry must precede exit; timestamps must be minute boundaries')
    stamps = range(plan['entry_ms'], plan['exit_ms'] + MINUTE, MINUTE)
    path = []
    for ts in stamps:
        price = prices.get(ts)
        if price is None or not math.isfinite(price) or price <= 0:
            raise ValueError(f'missing or invalid minute price: {plan["signal"]["inst"]} {ts}')
        path.append((ts, price))
    allocation = allocate(before, path[0][1], plan['signal'], plan['reference'], config, spec)
    if allocation is None:
        return None, []
    side, entry = plan['signal']['side'], path[0][1]
    units = allocation['quantity'] * allocation['unit_value']
    fee = config['fee_bps_per_side'] / 10000
    half_proxy = config['execution_proxy_bps_round_trip'] / 20000
    flows = {}
    for ts, rate in events:
        if plan['entry_ms'] < ts <= plan['exit_ms']:
            if ts % MINUTE or ts in flows or not math.isfinite(rate) or ts not in prices:
                raise ValueError('invalid, duplicate or unavailable carry settlement')
            flows[ts] = -side * rate * prices[ts]
    funding_unit = 0.0
    curve = []
    for ts, price in path:
        funding_unit += flows.get(ts, 0.0)
        value = (before + units * (side * (price - entry) + funding_unit)
                 - units * entry * (fee + half_proxy) - units * price * (fee + half_proxy))
        if not math.isfinite(value) or value <= 0:
            raise ValueError('nonpositive sampled equity; liquidation is not modeled')
        curve.append(dict(timestamp_ms=ts, equity=value))
    exit_price = path[-1][1]
    gross = units * side * (exit_price - entry)
    fees = units * (entry + exit_price) * fee
    proxy = units * (entry + exit_price) * half_proxy
    funding = units * funding_unit
    after = before + gross - fees - proxy + funding
    if not math.isclose(curve[-1]['equity'], after, rel_tol=1e-12, abs_tol=1e-10):
        raise ValueError('cash ledger and close-out curve disagree')
    trade = dict(symbol=plan['signal']['inst'], side=side, reference_symbol=plan['reference']['inst'],
                 signal_ms=plan['signal_ms'], entry_ms=plan['entry_ms'], exit_ms=plan['exit_ms'],
                 entry_price=entry, exit_price=exit_price, exit_reason=plan['exit_reason'],
                 sigma=plan['signal']['sigma'], sigma_floor=plan['sigma_floor'],
                 breach=plan['signal']['breach'], daily_vol=plan['signal']['daily_vol'],
                 **allocation, gross=gross, fees=fees, execution_cost_proxy=proxy, funding=funding,
                 equity_before=before, equity_after=after, pnl=after-before,
                 equity_return=after/before-1)
    return trade, curve


def replay(sessions, minutes, specs, config, carry_events=None, carry_coverage=None,
           carry_zero=False, start=None, end=None):
    config = validate_config(config)
    if (carry_zero and (carry_events is not None or carry_coverage is not None)) or (
            not carry_zero and (carry_events is None or carry_coverage is None)):
        raise ValueError('explicit zero carry OR events plus coverage required')
    if start and end and start > end:
        raise ValueError('start is after end')
    days = sorted(sessions)
    if len(days) < 16:
        raise ValueError('at least 15 warm-up sessions plus one evaluation session required')
    symbols = set(sessions[days[0]])
    if set(specs) != symbols or any(set(sessions[d]) != symbols for d in days):
        raise ValueError('complete, stable universe and matching specifications required')
    history = {symbol: [] for symbol in symbols}
    equity = peak_closed = peak_minute = config['initial_equity']
    closed_dd = minute_dd = 0.0
    trades, daily, curves, decisions = [], [], [], []
    for day in days:
        current = sessions[day]
        if len(next(iter(history.values()))) >= 15 and (start is None or day >= start) and (end is None or day <= end):
            plan = plan_session(history, current, config['version'])
            before = equity
            decision = dict(date=day.isoformat(), status='no_signal')
            if plan:
                symbol = plan['signal']['inst']
                if not carry_zero and not (carry_coverage[0] <= plan['entry_ms'] < plan['exit_ms'] <= carry_coverage[1]):
                    raise ValueError('holding period exceeds declared carry coverage')
                trade, curve = account_path(plan, equity, minutes.get(symbol, {}),
                                            [] if carry_zero else carry_events.get(symbol, []),
                                            config, specs[symbol])
                decision.update(symbol=symbol, reference_symbol=plan['reference']['inst'],
                                signal_ms=plan['signal_ms'], sigma_floor=plan['sigma_floor'],
                                target_exposure=plan['target_exposure'], status='executed_proxy' if trade else 'below_minimum')
                if trade:
                    trade['date'] = day.isoformat()
                    trades.append(trade)
                    equity = trade['equity_after']
                    for item in curve:
                        peak_minute = max(peak_minute, item['equity'])
                        dd = item['equity'] / peak_minute - 1
                        minute_dd = min(minute_dd, dd)
                        curves.append(dict(date=day.isoformat(), **item, drawdown=dd))
            decisions.append(decision)
            peak_closed = max(peak_closed, equity)
            peak_minute = max(peak_minute, equity)
            closed_dd = min(closed_dd, equity/peak_closed-1)
            daily.append(dict(date=day.isoformat(), equity_before=before, equity_after=equity,
                              equity_return=equity/before-1, closed_drawdown=equity/peak_closed-1))
        for symbol, item in current.items():
            history[symbol].append(item)
    if not daily:
        raise ValueError('no evaluation sessions in requested interval')
    summary = dict(strategy_version=config['version'], execution_protocol='minute_proxy_v2',
                   initial_equity=config['initial_equity'], final_equity=equity,
                   return_percent=100*(equity/config['initial_equity']-1),
                   max_closed_drawdown_percent=-100*closed_dd,
                   max_minute_sampled_closeout_drawdown_percent=-100*minute_dd,
                   evaluated_days=len(daily), trades=len(trades),
                   win_rate_percent=100*sum(t['pnl'] > 0 for t in trades)/len(trades) if trades else None,
                   mean_exposure=sum(t['exposure'] for t in trades)/len(trades) if trades else 0,
                   costs={key: sum(t[key] for t in trades) for key in ('gross', 'fees', 'execution_cost_proxy', 'funding')},
                   config=config,
                   carry_assumption='explicit_zero' if carry_zero else 'user_events_declared_coverage',
                   limitations=['Offline simulation; no actual fills or live performance.',
                                'Minute opens are price/settlement proxies; no order book, liquidation or partial fills.',
                                'Minute-sampled drawdown can miss intraminute extremes and mark-price moves.',
                                'Caller must verify calendar, timestamp availability, instrument specs and carry completeness.'])
    return dict(summary=summary, trades=trades, equity=daily, minute_equity=curves, decisions=decisions)
