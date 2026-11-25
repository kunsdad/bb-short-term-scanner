"""Archive exact daily scanner CSVs, optionally recovering past copies from git history.

No score recalculation; missing historical dates remain missing.
"""
import csv
import io
import json
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
ARCHIVE = DATA / 'snapshots'
START = '2026-11-23'
ARCHIVE.mkdir(parents=True, exist_ok=True)


def snapshot_day(blob):
    try:
        rows = csv.DictReader(io.StringIO(blob.decode('utf-8-sig')))
        dates = [r.get('date', '') for r in rows]
        day = max(dates) if dates else ''
        if not (day >= START and len(day) == 10 and date.fromisoformat(day)):
            return None
        return day
    except (UnicodeError, ValueError, csv.Error):
        return None


def add(blob, origin):
    day = snapshot_day(blob)
    if not day:
        return
    target = ARCHIVE / (day + '.csv')
    if not target.exists():
        target.write_bytes(blob)
        print(f'Archived {day} from {origin}', flush=True)


def recover_git_history():
    try:
        commits = subprocess.check_output(
            ['git', 'log', '--format=%H', '--', 'data/latest.csv'],
            cwd=ROOT, stderr=subprocess.DEVNULL, timeout=30, text=True
        ).splitlines()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        print('Git history unavailable; proceeding with existing snapshots.', flush=True)
        return
    for sha in commits[:300]:
        try:
            blob = subprocess.check_output(
                ['git', 'show', f'{sha}:data/latest.csv'],
                cwd=ROOT, stderr=subprocess.DEVNULL, timeout=15
            )
            add(blob, f'git {sha[:8]}')
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--recover', action='store_true')
    args = p.parse_args()
    if args.recover:
        recover_git_history()
    latest = DATA / 'latest.csv'
    if latest.exists():
        add(latest.read_bytes(), 'latest.csv')
    days = sorted(x.stem for x in ARCHIVE.glob('????-??-??.csv')
                  if x.stem >= START)
    (ARCHIVE / 'index.json').write_text(
        json.dumps({'dates': days, 'start_date': START}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8'
    )
    print(f'Archived dates: {", ".join(days) or "none"}', flush=True)


if __name__ == '__main__':
    main()
