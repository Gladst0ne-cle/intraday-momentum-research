"""Validate simulator bars and optionally compare an explicit session calendar."""
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ROOT
from simulate import load_bars


def check(bars, calendar=None):
    sessions = load_bars(bars)
    found = set(sessions)
    report = {'sessions': len(found), 'symbols': sorted(next(iter(sessions.values()))),
              'first_day': str(min(found)), 'last_day': str(max(found)),
              'calendar_checked': calendar is not None}
    if calendar:
        with Path(calendar).open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or 'date' not in reader.fieldnames:
                raise ValueError('Calendar must contain a date column')
            days = [date.fromisoformat(row['date']) for row in reader]
        if not days or len(days) != len(set(days)):
            raise ValueError('Calendar is empty or has duplicate dates')
        expected = set(days)
        report['missing_sessions'] = sorted(map(str, expected - found))
        report['unexpected_sessions'] = sorted(map(str, found - expected))
    report['limitations'] = 'Calendar is user supplied; this tool cannot prove source accuracy or detect all special sessions.'
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bars', required=True)
    p.add_argument('--calendar', help='CSV with one date column, scoped to exactly the data period')
    a = p.parse_args()
    result = check(a.bars, a.calendar)
    print(json.dumps(result, indent=2))
    if result.get('missing_sessions') or result.get('unexpected_sessions'):
        raise SystemExit(1)
