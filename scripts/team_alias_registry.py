from __future__ import annotations

import csv
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / 'data' / 'team_alias_registry.csv'
CURRENT = ROOT / 'data' / 'forebet_current.csv'
ARCHIVE = ROOT / 'data' / 'forebet_archive.csv'

FIELDS = [
    'team_key','canonical_name','source','alias','normalized_alias','confidence',
    'first_seen','last_seen','status'
]


def norm(value: str) -> str:
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace('&', ' and ')
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def team_key(name: str) -> str:
    return 'hkjc:' + norm(name).replace(' ', '-')


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))


def load_registry() -> tuple[dict[tuple[str,str],dict[str,str]], dict[str,str]]:
    rows: dict[tuple[str,str],dict[str,str]] = {}
    alias_to_key: dict[str,str] = {}
    for r in read_csv(REGISTRY):
        a = norm(r.get('alias',''))
        k = (r.get('team_key') or '').strip()
        if not a or not k:
            continue
        row = {f:(r.get(f) or '').strip() for f in FIELDS}
        rows[(k,a)] = row
        if row.get('status','ACTIVE') == 'ACTIVE':
            alias_to_key.setdefault(a,k)
    return rows, alias_to_key


def resolve_key(name: str, alias_to_key: dict[str,str]) -> str:
    n = norm(name)
    return alias_to_key.get(n) or team_key(name)


def add_alias(store, alias_to_key, canonical, source, alias, confidence, seen):
    canonical = (canonical or '').strip()
    alias = (alias or '').strip()
    if not canonical or not alias:
        return
    ck = alias_to_key.get(norm(canonical)) or alias_to_key.get(norm(alias)) or team_key(canonical)
    key = (ck, norm(alias))
    old = store.get(key)
    first = (old or {}).get('first_seen') or seen
    row = {
        'team_key': ck,
        'canonical_name': canonical,
        'source': source,
        'alias': alias,
        'normalized_alias': norm(alias),
        'confidence': f'{float(confidence):.3f}',
        'first_seen': first,
        'last_seen': seen,
        'status': 'ACTIVE',
    }
    store[key] = row
    alias_to_key[norm(alias)] = ck
    alias_to_key[norm(canonical)] = ck


def absorb_match_rows(store, alias_to_key, rows):
    seen = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for r in rows:
        try:
            score = float(r.get('match_score') or 1.0)
        except ValueError:
            score = 1.0
        # Only self-learn source aliases from an already accepted high-confidence match.
        if score < 0.90:
            continue
        for side in ('home','away'):
            canonical = (r.get(f'hkjc_{side}_team') or '').strip()
            zh = (r.get(f'hkjc_{side}_zh') or '').strip()
            fb = (r.get(f'{side}_team') or '').strip()
            if not canonical:
                continue
            add_alias(store,alias_to_key,canonical,'HKJC_EN',canonical,1.0,seen)
            add_alias(store,alias_to_key,canonical,'HKJC_ZH',zh,1.0,seen)
            add_alias(store,alias_to_key,canonical,'FOREBET',fb,score,seen)


def write_registry(store):
    REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    rows = sorted(store.values(), key=lambda r:(r['canonical_name'].casefold(),r['source'],r['alias'].casefold()))
    tmp = REGISTRY.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8-sig',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=FIELDS)
        w.writeheader(); w.writerows(rows)
    tmp.replace(REGISTRY)
    return rows


def alias_key_map() -> dict[str,str]:
    _, amap = load_registry()
    return amap


def main() -> int:
    store, amap = load_registry()
    absorb_match_rows(store,amap,read_csv(ARCHIVE))
    absorb_match_rows(store,amap,read_csv(CURRENT))
    rows=write_registry(store)
    print(f'TEAM_ALIAS_REGISTRY rows={len(rows)} teams={len({r["team_key"] for r in rows})}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
