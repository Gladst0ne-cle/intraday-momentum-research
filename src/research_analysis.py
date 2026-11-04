"""对离线模拟逐笔结果做描述性研究；不会修改策略或连接外部服务。"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from datetime import date
from pathlib import Path

from backtest import account


def finite(value, name):
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{name} 不是有效数字') from exc
    if not math.isfinite(result):
        raise ValueError(f'{name} 不是有限数字')
    return result


def load_trades(path, base_fee_bps):
    """读取模拟器输出，并核对时间顺序及原始费用公式。"""
    if not math.isfinite(base_fee_bps) or not 0 <= base_fee_bps < 10000:
        raise ValueError('原始费用不合法')
    required = {'date', 'inst', 'side', 'entry_ms', 'exit_ms', 'leverage',
                'gross_return', 'carry_return', 'equity_return', 'reason'}
    rows = []
    seen_days = set()
    with Path(path).open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError('逐笔 CSV 缺少必要列')
        for line, raw in enumerate(reader, 2):
            try:
                day = date.fromisoformat(raw['date'])
                entry, exit_ = int(raw['entry_ms']), int(raw['exit_ms'])
                side = int(raw['side'])
            except (ValueError, TypeError) as exc:
                raise ValueError(f'第 {line} 行日期、时间或方向无效') from exc
            leverage = finite(raw['leverage'], 'leverage')
            gross = finite(raw['gross_return'], 'gross_return')
            carry = finite(raw['carry_return'], 'carry_return')
            observed = finite(raw['equity_return'], 'equity_return')
            if not raw['inst'] or side not in (-1, 1) or not 0 < leverage <= 4 or not 0 < entry < exit_:
                raise ValueError(f'第 {line} 行标的、方向、杠杆或时间无效')
            if day in seen_days or (rows and (day <= rows[-1]['date'] or entry <= rows[-1]['exit_ms'])):
                raise ValueError('交易必须按日期顺序排列，且每天最多一笔、时间不重叠')
            expected = leverage * (gross + carry - base_fee_bps / 10000)
            if not math.isclose(observed, expected, rel_tol=1e-9, abs_tol=1e-10):
                raise ValueError(f'第 {line} 行收益与费用假设不一致')
            rows.append({'date': day, 'inst': raw['inst'], 'side': side, 'entry_ms': entry,
                         'exit_ms': exit_, 'leverage': leverage, 'gross_return': gross,
                         'carry_return': carry, 'equity_return': observed, 'reason': raw['reason']})
            seen_days.add(day)
    if not rows:
        raise ValueError('没有可分析的交易')
    return rows


def summary(rows, extra_bps=0):
    if not math.isfinite(extra_bps) or not 0 <= extra_bps < 10000:
        raise ValueError('额外成本不合法')
    adjusted = [r['equity_return'] - r['leverage'] * extra_bps / 10000 for r in rows]
    if any(x <= -1 for x in adjusted):
        return {'trades': len(rows), 'insolvency_in_scenario': True, 'wealth': None,
                'note': '该情景至少一笔收益达到或低于 -100%；程序不模拟强平'}
    stats = account([{'equity_return': x} for x in adjusted])
    wins = [x for x in adjusted if x > 0]
    losses = [x for x in adjusted if x < 0]
    stats.update({'insolvency_in_scenario': False, 'mean_win': statistics.mean(wins) if wins else None,
                  'mean_loss': statistics.mean(losses) if losses else None,
                  'average_exposure': statistics.mean(r['leverage'] for r in rows) if rows else None})
    return stats


def analyze(rows, extra_costs):
    if not rows:
        raise ValueError('没有可分析的交易')
    if not extra_costs or len(set(extra_costs)) != len(extra_costs):
        raise ValueError('额外成本列表不能为空或包含重复值')
    ranked = sorted(enumerate(rows), key=lambda pair: (-pair[1]['equity_return'], pair[0]))
    top = [pair for pair in ranked if pair[1]['equity_return'] > 0][:3]
    excluded = {i for i, _ in top}
    total = sum(r['equity_return'] for r in rows)
    top_sum = sum(r['equity_return'] for _, r in top)
    remaining = [r for i, r in enumerate(rows) if i not in excluded]
    mid = len(rows) // 2
    first, second = rows[:mid], rows[mid:]
    durations = [(r['exit_ms'] - r['entry_ms']) / 60000 for r in rows]
    reasons = {}
    for row in rows:
        reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
    return {
        'base': summary(rows),
        'extra_cost_scenarios_bps': {str(value): summary(rows, value) for value in extra_costs},
        'holding_minutes': {'mean': statistics.mean(durations), 'median': statistics.median(durations),
                            'min': min(durations), 'max': max(durations)},
        'exit_reasons': reasons,
        'concentration': {
            'largest_winning_trade_count': len(top), 'largest_wins_simple_return_sum': top_sum,
            'all_trades_simple_return_sum': total,
            'share_of_simple_return_sum_if_positive': top_sum / total if total > 0 else None,
            'remove_largest_winners_after_the_fact': summary(remaining) if remaining else None,
            'note': '事后剔除赢家仅为敏感性分析，不是可事先执行的策略；简单收益占比不是复利贡献占比。',
        },
        'chronological_halves': {
            'first': {'from': first[0]['date'].isoformat(), 'through': first[-1]['date'].isoformat(),
                      'statistics': summary(first)} if first else None,
            'second': {'from': second[0]['date'].isoformat(), 'through': second[-1]['date'].isoformat(),
                       'statistics': summary(second)} if second else None,
            'note': '按交易时间顺序分段，不是重新训练，也不是独立样本外验证。',
        },
        'limitations': ['成本压力仅改变费用假设，不模拟真实执行或冲击',
                        '回撤只在交易完成后计算，不代表盘中最大损失',
                        '无交易日未包含在逐笔文件中，不能据此推算每日收益'],
    }


def main():
    parser = argparse.ArgumentParser(description='分析本仓库模拟器生成的逐笔交易')
    parser.add_argument('--trades', type=Path, required=True)
    parser.add_argument('--summary', type=Path, required=True, help='同一模拟产生的 summary.json')
    parser.add_argument('--extra-bps', type=float, nargs='+', default=[0, 5, 20])
    parser.add_argument('--output', type=Path, default=Path('output/research-analysis.json'))
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        metadata = json.loads(args.summary.read_text(encoding='utf-8'))
        base_fee = finite(metadata['round_trip_fee_bps'], 'round_trip_fee_bps')
        rows = load_trades(args.trades, base_fee)
        if metadata.get('trades') != len(rows):
            raise ValueError('summary.json 与逐笔交易数量不一致')
        report = analyze(rows, args.extra_bps)
        report['input_context'] = {'data_type': metadata.get('data_type', 'unknown'),
                                   'carry_assumption': metadata.get('carry_assumption', 'unknown'),
                                   'base_round_trip_fee_bps': base_fee}
        if args.output.resolve() in {args.trades.resolve(), args.summary.resolve()}:
            raise ValueError('分析输出不能覆盖输入文件')
        if args.output.exists() and not args.overwrite:
            raise ValueError('分析输出已存在；更换 --output 或使用 --overwrite')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(json.dumps({'output': str(args.output), 'trades': len(rows)}, ensure_ascii=False))
    except (ValueError, OSError, KeyError, csv.Error, json.JSONDecodeError) as exc:
        parser.exit(2, f'分析未完成：{exc}\n')


if __name__ == '__main__':
    main()
