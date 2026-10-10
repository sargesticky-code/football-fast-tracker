"""Locally snapshotted, source-verified Forebet aliases. Never fuzzy match.

Only existing VERIFIED registry aliases, >=0.95 confidence and a unique
team_key are eligible. Runtime reads a 54KB repository JSON file: no new
Supabase request, source scrape, database table or scheduled task.
"""
import json
import unicodedata
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def catalog():
    data=json.loads((Path(__file__).resolve().parent.parent/
                     "data/forebet_verified_aliases.json").read_text(encoding="utf-8"))
    if data.get("snapshot_type")!="VERIFIED_SOURCE_ALIAS_KEYS_ONLY":
        raise ValueError("FOREBET_ALIASES_UNVERIFIED")
    fb=data["forebet_source"]
    target=data["verified_target_names"]
    if len(fb)<400 or len(target)<650:
        raise ValueError("FOREBET_ALIASES_INCOMPLETE")
    by_key={}
    for alias,key in fb.items():
        by_key.setdefault(key,[]).append(alias)
    return fb,target,{k:sorted(v) for k,v in by_key.items()}

def norm(value):
    s=unicodedata.normalize("NFKD",str(value or "")).casefold()
    return "".join(c for c in s if c.isalnum() and not unicodedata.combining(c))

def target_team_key(name):
    _,canon,by_key=catalog()
    n=norm(name)
    # Never infer an unseen team solely from spelling. The derived HKJC:
    # identifier here is a legacy canonical key, not an HKJC source request.
    return canon.get(n) or (("HKJC:"+n) if ("HKJC:"+n) in by_key else None)

def source_forms(name):
    _,_,by_key=catalog()
    n=norm(name)
    key=target_team_key(name)
    # Unmatched teams retain the safe original exact-name path.
    forms=[n]+(by_key.get(key,[]) if key else [])
    return sorted(set(forms))[:16]

def verified_source_name(source,target):
    a,b=norm(source),norm(target)
    if a==b and a: return True
    fb,_,_=catalog()
    key=target_team_key(target)
    return bool(key and fb.get(a)==key)
