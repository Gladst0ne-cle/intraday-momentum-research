"""CSV adapters and CLI for the versioned offline replay."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from simulate import finite_float, load_bars, save_synthetic_bars, synthetic_sessions, timestamp_ms
from versioned_replay import DEFAULTS, MINUTE, replay, validate_config


def rows_from_csv(path, required):
    with Path(path).open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
            raise ValueError(f'{Path(path).name}: required columns: {", ".join(required)}')
        return list(reader)


def load_minutes(path):
    minutes = {}
    for row in rows_from_csv(path, ['symbol', 'timestamp_ms', 'open', 'high', 'low', 'close']):
        symbol = row['symbol'].strip()
        ts = timestamp_ms(row['timestamp_ms'])
        o, h, l, c = [finite_float(row[k], k) for k in ('open', 'high', 'low', 'close')]
        if not symbol or ts % MINUTE or min(o, h, l, c) <= 0 or h < max(o, l, c) or l > min(o, c):
            raise ValueError('invalid minute timestamp or OHLC')
        series = minutes.setdefault(symbol, {})
        if ts in series:
            raise ValueError('duplicate minute row')
        series[ts] = o
    if not minutes:
        raise ValueError('empty minute file')
    return minutes


def load_specs(path):
    specs = {}
    fields = ['quantity_step', 'minimum_quantity', 'unit_value']
    for row in rows_from_csv(path, ['symbol', *fields]):
        symbol = row['symbol'].strip()
        if not symbol or symbol in specs:
            raise ValueError('missing or duplicate specification symbol')
        values = {key: finite_float(row[key], key) for key in fields}
        if any(value <= 0 for value in values.values()):
            raise ValueError('specification values must be positive')
        specs[symbol] = values
    return specs


def load_events(path, first, last):
    first, last = timestamp_ms(first), timestamp_ms(last)
    if first > last:
        raise ValueError('invalid carry coverage')
    events, seen = {}, set()
    for row in rows_from_csv(path, ['symbol', 'timestamp_ms', 'rate']):
        symbol = row['symbol'].strip()
        ts, rate = timestamp_ms(row['timestamp_ms']), finite_float(row['rate'], 'rate')
        if not symbol or ts % MINUTE or not first <= ts <= last or (symbol, ts) in seen:
            raise ValueError('invalid or duplicate carry event')
        seen.add((symbol, ts))
        events.setdefault(symbol, []).append((ts, rate))
    return events, (first, last)


def demo_inputs():
    """Interpolate fictional bars, not observed intrabar market paths.

    The final minute closes at the half-hour close; the next minute opens at
    the next bar's opening. Minute high/low envelopes preserve the parent bar.
    """
    sessions = synthetic_sessions()
    minutes, minute_rows = {}, []
    for day, symbols in sorted(sessions.items()):
        for symbol, session in sorted(symbols.items()):
            series = minutes.setdefault(symbol, {})
            for bar in session['bars']:
                ts, opening, high, low, close, _ = bar
                for j in range(30):
                    o = opening + (close-opening)*j/30
                    c = opening + (close-opening)*(j+1)/30
                    t = ts+j*MINUTE
                    series[t] = o
                    minute_rows.append(dict(symbol=symbol, timestamp_ms=t, open=o, high=high,
                                            low=low, close=c))
            ts, px = session['session_end']
            for j in range(2):
                series[ts+j*MINUTE] = px
                minute_rows.append(dict(symbol=symbol, timestamp_ms=ts+j*MINUTE,
                                        open=px, high=px, low=px, close=px))
    specs = {symbol: dict(quantity_step=.01, minimum_quantity=.01, unit_value=1)
             for symbol in next(iter(sessions.values()))}
    return sessions, minutes, specs, minute_rows


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ['date']
    with Path(path).open('w', encoding='utf-8', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def save_results(directory, result):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'summary.json').write_text(json.dumps(result['summary'], indent=2, allow_nan=False)+'\n', encoding='utf-8')
    for name in ('trades', 'equity', 'minute_equity', 'decisions'):
        write_csv(directory / (name+'.csv'), result[name])


def main(argv=None):
    parser = argparse.ArgumentParser(description='Versioned offline momentum simulation; no accounts or orders.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--demo', action='store_true')
    source.add_argument('--bars', type=Path)
    parser.add_argument('--minutes', type=Path)
    parser.add_argument('--specs', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--compare', action='store_true', help='Both signal rules under the SAME minute execution protocol')
    parser.add_argument('--initial-equity', type=float)
    parser.add_argument('--extra-cost-bps', type=float, default=0, help='Additional round-trip execution proxy, not commission')
    carry = parser.add_mutually_exclusive_group()
    carry.add_argument('--carry-zero', action='store_true')
    carry.add_argument('--carry-file', type=Path)
    parser.add_argument('--carry-coverage-start')
    parser.add_argument('--carry-coverage-end')
    parser.add_argument('--start', type=date.fromisoformat)
    parser.add_argument('--end', type=date.fromisoformat)
    parser.add_argument('--export-example', type=Path)
    parser.add_argument('--output', type=Path, default=Path('output/versioned'))
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding='utf-8')) if args.config else dict(DEFAULTS)
        validate_config(config)
        if args.initial_equity is not None:
            config['initial_equity'] = args.initial_equity
        extra = finite_float(args.extra_cost_bps, 'extra-cost-bps')
        if extra < 0:
            raise ValueError('extra cost cannot be negative')
        config['execution_proxy_bps_round_trip'] += extra
        validate_config(config)
        if args.demo:
            if any((args.minutes, args.specs, args.carry_file, args.carry_coverage_start, args.carry_coverage_end)):
                raise ValueError('--demo does not accept external market/specification/carry files')
            sessions, minutes, specs, example_rows = demo_inputs()
            events = coverage = None
            zero = True
        else:
            if not args.minutes or not args.specs or args.export_example:
                raise ValueError('--bars requires --minutes and --specs; export is demo-only')
            sessions, minutes, specs = load_bars(args.bars), load_minutes(args.minutes), load_specs(args.specs)
            if args.carry_zero:
                if args.carry_coverage_start or args.carry_coverage_end:
                    raise ValueError('zero carry cannot have coverage arguments')
                events = coverage = None
                zero = True
            elif args.carry_file and args.carry_coverage_start and args.carry_coverage_end:
                events, coverage = load_events(args.carry_file, args.carry_coverage_start, args.carry_coverage_end)
                if set(events) - set(specs):
                    raise ValueError('carry contains unknown symbols')
                zero = False
            else:
                raise ValueError('select --carry-zero or provide carry file AND start/end coverage')
        versions = ['v1.0.0', 'v1.1.0'] if args.compare else [config['version']]
        directories = [args.output / v for v in versions] if args.compare else [args.output]
        targets = [directory / file for directory in directories
                   for file in ('summary.json', 'trades.csv', 'equity.csv', 'minute_equity.csv', 'decisions.csv')]
        if args.compare:
            targets.append(args.output / 'comparison.json')
        if args.export_example:
            targets.extend(args.export_example / name for name in ('bars30.csv', 'minutes.csv', 'specs.csv'))
        inputs = [p.resolve() for p in (args.bars, args.minutes, args.specs, args.carry_file, args.config) if p]
        resolved = [p.resolve() for p in targets]
        if len(set(resolved)) != len(resolved) or set(resolved) & set(inputs):
            raise ValueError('output paths overlap each other or an input')
        if not args.overwrite and any(p.exists() for p in targets):
            raise ValueError('output exists; select another --output or explicitly use --overwrite')
        provenance = {role: hashlib.sha256(path.read_bytes()).hexdigest()
                      for role, path in [('bars', args.bars), ('minutes', args.minutes),
                                         ('specs', args.specs), ('carry', args.carry_file),
                                         ('config', args.config)] if path}
        results = []
        # Compute all results before writing: a missing minute cannot leave a partial comparison.
        for version in versions:
            result = replay(sessions, minutes, specs, {**config, 'version': version},
                            events, coverage, zero, args.start, args.end)
            result['summary'].update(data_type='synthetic_demo' if args.demo else 'user_supplied',
                                     input_sha256=provenance)
            results.append(result)
        for directory, result in zip(directories, results):
            save_results(directory, result)
        if args.compare:
            comparison = dict(protocol='minute_proxy_v2',
                              note='Aligned signal-rule comparison; not the legacy 53-trade historical summary.',
                              versions={r['summary']['strategy_version']: r['summary'] for r in results})
            (args.output / 'comparison.json').write_text(json.dumps(comparison, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        if args.export_example:
            args.export_example.mkdir(parents=True, exist_ok=True)
            save_synthetic_bars(args.export_example / 'bars30.csv', sessions, args.overwrite)
            write_csv(args.export_example / 'minutes.csv', example_rows)
            write_csv(args.export_example / 'specs.csv', [dict(symbol=symbol, **spec) for symbol, spec in sorted(specs.items())])
        for result in results:
            s = result['summary']
            print(f"{s['strategy_version']} | {s['data_type']} | trades={s['trades']} | return={s['return_percent']:.4f}% | closed DD={s['max_closed_drawdown_percent']:.4f}% | minute DD={s['max_minute_sampled_closeout_drawdown_percent']:.4f}%")
        print(f'Results: {args.output}')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
