from __future__ import annotations

import argparse
import csv
import io
import subprocess
from pathlib import Path

ARCHIVE = Path('data/forebet_archive.csv')
CURRENT = Path('data/forebet_current.csv')
PREDICTION_ARCHIVE = Path('data/prediction_archive.csv')

FIELDS = [
    'captured_at_hkt','hkjc_event_id','hkjc_league','hkjc_home_team','hkjc_away_team',
    'hkjc_home_zh','hkjc_away_zh','hkjc_kickoff_hkt','prob_home','prob_draw','prob_away',
    'prediction_1x2','predicted_score','avg_goals','power_home','power_away','power_source','power_updated'
]


def clean(v):
    return (v or '').strip()


def map_forebet(r):
    return {
        'captured_at_hkt': clean(r.get('fetched_at_hkt')),
        'hkjc_event_id': clean(r.get('hkjc_event_id')),
        'hkjc_league': clean(r.get('hkjc_league')),
        'hkjc_home_team': clean(r.get('hkjc_home_team')),
        'hkjc_away_team': clean(r.get('hkjc_away_team')),
        'hkjc_home_zh': clean(r.get('hkjc_home_zh')),
        'hkjc_away_zh': clean(r.get('hkjc_away_zh')),
        'hkjc_kickoff_hkt': clean(r.get('hkjc_kickoff_hkt')),
        'prob_home': clean(r.get('prob_home')),
        'prob_draw': clean(r.get('prob_draw')),
        'prob_away': clean(r.get('prob_away')),
        'prediction_1x2': clean(r.get('prediction_1x2')),
        'predicted_score': clean(r.get('predicted_score')),
        'avg_goals': clean(r.get('avg_goals')),
        'power_home': clean(r.get('power_home')),
        'power_away': clean(r.get('power_away')),
        'power_source': clean(r.get('power_source')),
        'power_updated': clean(r.get('power_updated')),
    }


def map_prediction(r):
    return {
        'captured_at_hkt': clean(r.get('captured_at_hkt')),
        'hkjc_event_id': clean(r.get('hkjc_event_id')),
        'hkjc_league': clean(r.get('league')),
        'hkjc_home_team': clean(r.get('home')),
        'hkjc_away_team': clean(r.get('away')),
        'hkjc_home_zh': '',
        'hkjc_away_zh': '',
        'hkjc_kickoff_hkt': clean(r.get('kickoff_hkt')),
        'prob_home': clean(r.get('forebet_home')),
        'prob_draw': clean(r.get('forebet_draw')),
        'prob_away': clean(r.get('forebet_away')),
        'prediction_1x2': clean(r.get('forebet_pick')),
        'predicted_score': '',
        'avg_goals': '',
        'power_home': clean(r.get('opta_home')),
        'power_away': clean(r.get('opta_away')),
        'power_source': 'Opta Power Rankings' if clean(r.get('opta_home')) or clean(r.get('opta_away')) else '',
        'power_updated': '',
    }


def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))


def read_git_ref(ref):
    if not ref:
        return []
    try:
        raw = subprocess.check_output(['git','show',f'{ref}:data/forebet_current.csv'], text=True, encoding='utf-8-sig')
    except Exception as exc:
        print(f'WARN bootstrap ref unavailable: {exc}')
        return []
    return list(csv.DictReader(io.StringIO(raw)))


def merge_row(store, row):
    event_id = clean(row.get('hkjc_event_id'))
    if not event_id:
        return
    if not all(clean(row.get(k)) for k in ('prob_home','prob_draw','prob_away')):
        return
    store[event_id] = {k: clean(row.get(k)) for k in FIELDS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bootstrap-ref', default='')
    args = ap.parse_args()

    store = {}
    for r in read_csv(ARCHIVE):
        merge_row(store, r)
    for r in read_git_ref(args.bootstrap_ref):
        merge_row(store, map_forebet(r))
    for r in read_csv(PREDICTION_ARCHIVE):
        merge_row(store, map_prediction(r))
    for r in read_csv(CURRENT):
        merge_row(store, map_forebet(r))

    rows = sorted(store.values(), key=lambda r: (r.get('hkjc_kickoff_hkt',''), r.get('hkjc_event_id','')))
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVE.open('w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f'FOREBET_ARCHIVE rows={len(rows)} current={len(read_csv(CURRENT))}')

if __name__ == '__main__':
    main()
