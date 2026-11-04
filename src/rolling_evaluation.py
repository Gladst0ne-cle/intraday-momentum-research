"""按时间顺序将固定规则分段回测；不训练模型或选择参数。"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from simulate import load_bars, load_carry, simulate, synthetic_sessions

HISTORY_SESSIONS = 15


def evaluate(sessions, carry, fold_days=5, fee_bps=10.0):
    if type(fold_days) is not int or fold_days <= 0:
        raise ValueError('每段交易日数必须为正整数')
    days = sorted(sessions)
    if len(days) <= HISTORY_SESSIONS:
        raise ValueError('至少需要 15 个历史交易日和 1 个评估交易日')
    folds = []
    for start in range(HISTORY_SESSIONS, len(days), fold_days):
        end = min(start + fold_days, len(days))
        # Keep prior inputs only; no bar after this fold is visible to its run.
        available = {day: sessions[day] for day in days[:end]}
        trades, result = simulate(available, carry, fee_bps=fee_bps, initial_equity=1.0,
                                  start=days[start], end=days[end - 1])
        folds.append({'first_day': days[start].isoformat(), 'last_day': days[end - 1].isoformat(),
                      'prior_sessions': start, 'evaluated_days': result['evaluated_days'],
                      'trades': len(trades), 'return': result['return'],
                      'max_drawdown_after_completed_trades': result['max_drawdown_after_completed_trades'],
                      'win_rate': result['win_rate'], 'partial_final_fold': end - start < fold_days})
    return {'fold_days': fold_days, 'folds': folds,
            'limitations': ['固定规则的连续分段表现；没有重新训练或参数选择',
                            '若数据或参数曾用于研究，分段结果不是新的独立样本外验证',
                            '每段权益从 1 重置；每段最大回撤只在交易完成后计算']}


def main():
    parser = argparse.ArgumentParser(description='按完整交易日顺序分段评估固定策略')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--demo', action='store_true')
    source.add_argument('--bars', type=Path)
    carry_group = parser.add_mutually_exclusive_group()
    carry_group.add_argument('--carry-zero', action='store_true')
    carry_group.add_argument('--carry-file', type=Path)
    parser.add_argument('--carry-coverage-start')
    parser.add_argument('--carry-coverage-end')
    parser.add_argument('--fold-days', type=int, default=5)
    parser.add_argument('--fee-bps', type=float, default=10.0)
    parser.add_argument('--output', type=Path, default=Path('output/rolling-evaluation.json'))
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        if args.demo:
            if args.carry_file or args.carry_coverage_start or args.carry_coverage_end:
                raise ValueError('虚构示例不接受真实费用文件')
            sessions, carry = synthetic_sessions(), lambda *_: 0.0
            data_type, carry_note = 'synthetic_demo', '虚构示例假定持仓费用为零'
        else:
            sessions = load_bars(args.bars)
            if args.carry_zero:
                if args.carry_coverage_start or args.carry_coverage_end:
                    raise ValueError('假定为零时无需提供费用覆盖范围')
                carry, carry_note = lambda *_: 0.0, '用户明确假定持仓费用为零，未经验证'
            elif args.carry_file and args.carry_coverage_start and args.carry_coverage_end:
                carry = load_carry(args.carry_file, args.carry_coverage_start, args.carry_coverage_end)
                carry_note = '用户提供费用和覆盖声明；完整性未经独立验证'
            else:
                raise ValueError('请明确选择费用假设，或提供费用文件及覆盖范围')
            data_type = 'user_supplied'
        if not math.isfinite(args.fee_bps):
            raise ValueError('费用必须为有限数字')
        report = evaluate(sessions, carry, args.fold_days, args.fee_bps)
        report.update({'data_type': data_type, 'carry_assumption': carry_note,
                       'round_trip_fee_bps': args.fee_bps})
        inputs = {p.resolve() for p in (args.bars, args.carry_file) if p}
        if args.output.resolve() in inputs:
            raise ValueError('输出不能覆盖输入文件')
        if args.output.exists() and not args.overwrite:
            raise ValueError('输出已存在；更换 --output 或使用 --overwrite')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(json.dumps({'output': str(args.output), 'fold_count': len(report['folds'])}, ensure_ascii=False))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'分段评估未完成：{exc}\n')


if __name__ == '__main__':
    main()
