"""多交易日离线模拟；不连接账户，不发送订单。"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backtest import BAR_MS, account, run_session


def new_york():
    try:
        return ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError as exc:
        raise ValueError('缺少时区数据库；请先运行 python -m pip install tzdata') from exc


def timestamp_ms(value):
    try:
        value = int(value)
        datetime.fromtimestamp(value / 1000, timezone.utc)
        return value
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise ValueError('timestamp_ms 必须是有效的 Unix 毫秒时间戳') from exc


def finite_float(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field} 必须为数字') from exc
    if not math.isfinite(number):
        raise ValueError(f'{field} 必须为有限数字')
    return number


def load_bars(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        required = {'symbol', 'timestamp_ms', 'open', 'high', 'low', 'close', 'volume'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError('行情 CSV 缺少必需列')
        return build_sessions(reader)


def build_sessions(rows):
    zone = new_york()
    grouped = defaultdict(dict)
    symbols = set()
    for line, row in enumerate(rows, 2):
        symbol = str(row.get('symbol', '')).strip()
        if not symbol:
            raise ValueError(f'第 {line} 行缺少 symbol')
        ts = timestamp_ms(row.get('timestamp_ms'))
        local = datetime.fromtimestamp(ts / 1000, zone)
        opening, high, low, close, volume = [finite_float(row.get(k), k) for k in ('open', 'high', 'low', 'close', 'volume')]
        if min(opening, high, low, close) <= 0 or high < max(opening, low, close) or low > min(opening, close) or volume < 0:
            raise ValueError(f'第 {line} 行 OHLCV 无效')
        key = (local.date(), symbol)
        if ts in grouped[key]:
            raise ValueError(f'第 {line} 行时间戳重复')
        grouped[key][ts] = (ts, opening, high, low, close, volume)
        symbols.add(symbol)
    if not grouped:
        raise ValueError('行情为空')
    days = sorted({key[0] for key in grouped})
    result = {}
    for day in days:
        opening = datetime(day.year, day.month, day.day, 9, 30, tzinfo=zone)
        expected = [int((opening + timedelta(minutes=30 * i)).timestamp() * 1000) for i in range(14)]
        by_symbol = {}
        for symbol in sorted(symbols):
            bars = grouped.get((day, symbol), {})
            if sorted(bars) != expected:
                raise ValueError(f'{day} {symbol} 缺少完整的 09:30–16:00 半小时行情')
            intraday = [bars[t] for t in expected[:-1]]
            by_symbol[symbol] = {'open': intraday[0][1], 'close': intraday[-1][4],
                                 'bars': intraday, 'session_end': (expected[-1], bars[expected[-1]][1])}
        result[day] = by_symbol
    return result


def synthetic_sessions():
    """只生成虚构示例，不使用真实行情。"""
    zone = new_york()
    rng = random.Random(319)
    day = date(2026, 1, 5)
    prices = {'AAA': 100.0, 'BBB': 80.0, 'CCC': 120.0}
    rows = []
    generated = 0
    while generated < 26:
        if day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        for symbol in sorted(prices):
            current = prices[symbol] * (1 + rng.uniform(-.008, .008))
            direction = 1 if (generated + len(symbol)) % 4 in (0, 1) else -1
            for i in range(14):
                ts = int(datetime(day.year, day.month, day.day, 9, 30, tzinfo=zone).timestamp() * 1000) + i * BAR_MS
                opening = current
                if generated % 4 == 0 and i == 0:
                    change = direction * .03
                elif generated % 4 == 0 and 1 <= i < 4:
                    change = -direction * .015
                else:
                    change = direction * rng.uniform(.0002, .003) if i < 13 else 0.0
                current = opening * (1 + change)
                rows.append({'symbol': symbol, 'timestamp_ms': ts, 'open': opening,
                             'high': max(opening, current) * 1.0005, 'low': min(opening, current) * .9995,
                             'close': current, 'volume': 1000 + i * 10})
            prices[symbol] = current
        generated += 1
        day += timedelta(days=1)
    return build_sessions(rows)


def save_synthetic_bars(path, sessions, overwrite=False):
    """将虚构行情导出为可复用的 CSV 格式示例。"""
    path = Path(path)
    if path.exists() and not overwrite:
        raise ValueError('示例行情输出已存在；更换路径或明确使用 --overwrite')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as out:
        fields = ['symbol', 'timestamp_ms', 'open', 'high', 'low', 'close', 'volume']
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for _day, symbols in sorted(sessions.items()):
            for symbol, item in sorted(symbols.items()):
                for ts, opening, high, low, close, volume in item['bars']:
                    writer.writerow(dict(symbol=symbol, timestamp_ms=ts, open=opening, high=high,
                                         low=low, close=close, volume=volume))
                ts, opening = item['session_end']
                writer.writerow(dict(symbol=symbol, timestamp_ms=ts, open=opening, high=opening,
                                     low=opening, close=opening, volume=0))


def load_carry(path, coverage_start, coverage_end):
    first, last = timestamp_ms(coverage_start), timestamp_ms(coverage_end)
    if first > last:
        raise ValueError('carry 覆盖开始时间晚于结束时间')
    events = defaultdict(list)
    seen = set()
    with Path(path).open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not {'symbol', 'timestamp_ms', 'rate'}.issubset(reader.fieldnames):
            raise ValueError('carry CSV 缺少必需列')
        for row in reader:
            symbol = str(row.get('symbol', '')).strip()
            ts, rate = timestamp_ms(row.get('timestamp_ms')), finite_float(row.get('rate'), 'rate')
            if not symbol or (symbol, ts) in seen or not first <= ts <= last:
                raise ValueError('carry 事件为空、重复或位于声明覆盖范围之外')
            seen.add((symbol, ts))
            events[symbol].append((ts, rate))

    def carry(symbol, side, entry_ms, exit_ms):
        if entry_ms < first or exit_ms > last:
            raise ValueError(f'{symbol} 的持仓时间超过声明的 carry 覆盖范围')
        return sum(-side * rate for ts, rate in events.get(symbol, []) if entry_ms < ts <= exit_ms)

    return carry


def simulate(sessions, carry, fee_bps=10.0, initial_equity=10000.0, start=None, end=None):
    if not math.isfinite(fee_bps) or not 0 <= fee_bps < 10000:
        raise ValueError('往返手续费必须在 0 到 10000 基点之间')
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError('初始权益必须为正数')
    if start and end and start > end:
        raise ValueError('开始日期晚于结束日期')
    days = sorted(sessions)
    if len(days) < 16:
        raise ValueError('至少需要 15 个历史交易日和 1 个模拟交易日')
    history = {symbol: [] for symbol in sessions[days[0]]}
    trades = []
    evaluated = 0
    for day in days:
        current = sessions[day]
        if len(next(iter(history.values()))) >= 15 and (start is None or day >= start) and (end is None or day <= end):
            bars = {s: item['bars'] for s, item in current.items()}
            closes = {s: item['session_end'] for s, item in current.items()}
            trade = run_session(history, bars, closes, carry, round_trip_fee=fee_bps / 10000)
            evaluated += 1
            if trade:
                trades.append({'date': day.isoformat(), **trade})
        for symbol, value in current.items():
            history[symbol].append({'open': value['open'], 'close': value['close'], 'bars': value['bars']})
    if not evaluated:
        raise ValueError('指定区间没有可模拟日期；请保留至少 15 个此前交易日')
    totals = account(trades)
    equity = initial_equity
    for trade in trades:
        trade['equity_before'] = equity
        equity *= 1 + trade['equity_return']
        trade['equity_after'] = equity
        trade['pnl'] = trade['equity_after'] - trade['equity_before']
    return trades, {**totals, 'evaluated_days': evaluated, 'initial_equity': initial_equity,
                    'final_equity': equity, 'round_trip_fee_bps': fee_bps}


def main():
    parser = argparse.ArgumentParser(description='30 分钟策略离线模拟；不连接实盘')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--demo', action='store_true', help='使用内置的虚构数据')
    source.add_argument('--bars', type=Path, help='读取用户提供的行情 CSV')
    parser.add_argument('--save-demo-bars', type=Path, help='可选：导出虚构行情 CSV，供参考格式')
    carry_group = parser.add_mutually_exclusive_group()
    carry_group.add_argument('--carry-zero', action='store_true', help='明确假定持仓费用为零')
    carry_group.add_argument('--carry-file', type=Path, help='读取持仓费用事件 CSV')
    parser.add_argument('--carry-coverage-start', help='费用文件覆盖起点，Unix 毫秒')
    parser.add_argument('--carry-coverage-end', help='费用文件覆盖终点，Unix 毫秒')
    parser.add_argument('--start', type=date.fromisoformat)
    parser.add_argument('--end', type=date.fromisoformat)
    parser.add_argument('--initial-equity', type=float, default=10000.0)
    parser.add_argument('--fee-bps', type=float, default=10.0)
    parser.add_argument('--output', type=Path, default=Path('output/simulation'))
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        if args.demo:
            if args.carry_file or args.carry_coverage_start or args.carry_coverage_end:
                raise ValueError('虚构示例不接受真实费用文件')
            sessions = synthetic_sessions()
            carry = lambda *_: 0.0
            carry_note = '虚构示例假定为零，不代表真实费用'
        else:
            if args.save_demo_bars:
                raise ValueError('--save-demo-bars 仅适用于 --demo')
            sessions = load_bars(args.bars)
            if args.carry_zero:
                if args.carry_coverage_start or args.carry_coverage_end:
                    raise ValueError('假定为零时无需填写费用覆盖范围')
                carry = lambda *_: 0.0
                carry_note = '用户明确假定为零，未经验证'
            elif args.carry_file and args.carry_coverage_start and args.carry_coverage_end:
                carry = load_carry(args.carry_file, args.carry_coverage_start, args.carry_coverage_end)
                carry_note = '按用户提供的事件与声明覆盖范围计算，完整性未独立验证'
            else:
                raise ValueError('请明确选择 --carry-zero，或提供费用文件及覆盖起止时间')
        trades, summary = simulate(sessions, carry, args.fee_bps, args.initial_equity, args.start, args.end)
        summary.update({'data_type': 'synthetic_demo' if args.demo else 'user_supplied', 'carry_assumption': carry_note,
                        'limitations': ['价格为下一根半小时开盘代理；不模拟排队、冲击、保证金或强平',
                                        '最大回撤仅按交易结束后的权益计算', '用户自行核实行情可用时间、市场日历和费用覆盖']})
        args.output.mkdir(parents=True, exist_ok=True)
        trades_path, summary_path = args.output / 'trades.csv', args.output / 'summary.json'
        protected = [p.resolve() for p in (args.bars, args.carry_file, args.save_demo_bars) if p]
        if trades_path.resolve() in protected or summary_path.resolve() in protected:
            raise ValueError('输出文件不能与输入或示例行情路径相同')
        if not args.overwrite and (trades_path.exists() or summary_path.exists()):
            raise ValueError('输出已存在；更改 --output 或明确使用 --overwrite')
        if args.save_demo_bars:
            save_synthetic_bars(args.save_demo_bars, sessions, args.overwrite)
        fields = ['date', 'inst', 'side', 'entry_ms', 'entry_px', 'exit_ms', 'exit_px', 'leverage',
                  'gross_return', 'carry_return', 'equity_return', 'reason', 'equity_before', 'pnl', 'equity_after']
        with trades_path.open('w', encoding='utf-8', newline='') as out:
            writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(trades)
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
        print(json.dumps({'trades_file': str(trades_path), 'summary_file': str(summary_path), **summary}, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, csv.Error) as exc:
        parser.exit(2, f'模拟未完成：{exc}\n')


if __name__ == '__main__':
    main()
