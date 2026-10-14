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


@lru_cache(maxsize=1)
def shared_verified_catalog():
    """Offline, provenance-checked bridge from two verified provider namespaces.

    Identifiers are opaque hashes, not a live HKJC dependency.
    """
    data=json.loads((Path(__file__).resolve().parent.parent /
         "data/forebet_flashscore_shared_verified_keys.json").read_text(encoding="utf-8"))
    if (data.get("snapshot_type")!="FOREBET_FLASHSCORE_SHARED_VERIFIED_TEAM_KEYS_V1"
        or data.get("policy")!="VERIFIED_ONLY_UNIQUE_NAME_KEYS_CONFIDENCE_GTE_0.95_OFFLINE"
        or data.get("shared_team_keys",0)<400):
        raise ValueError("CROSS_PROVIDER_ALIAS_PROVENANCE_UNVERIFIED")
    fs=data["provider_names"]["FLASHSCORE"]
    fb=data["provider_names"]["FOREBET"]
    if len(fs)<450 or len(fb)<500:
        raise ValueError("CROSS_PROVIDER_ALIAS_COVERAGE_INCOMPLETE")
    for provider in (fs,fb):
        if any(not isinstance(k,str) or k!=norm(k) or
               not isinstance(v,str) or len(v)!=32 or
               any(ch not in "0123456789abcdef" for ch in v)
               for k,v in provider.items()):
            raise ValueError("CROSS_PROVIDER_ALIAS_INVALID_KEY")
    ids=set(fs.values()) & set(fb.values())
    by_key={}
    for alias,key in fb.items():
        if key in ids:
            by_key.setdefault(key,set()).add(alias)
    return fs,fb,{key:sorted(names) for key,names in by_key.items()}


def verified_shared_source_name(source,target):
    fs,fb,_=shared_verified_catalog()
    sk=fb.get(norm(source))
    tk=fs.get(norm(target))
    if sk is None or tk is None:
        return None
    return sk==tk

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
    fs,fb,shared=shared_verified_catalog()
    verified_key=fs.get(n)
    if verified_key:
        forms.extend(shared.get(verified_key,[]))
    return [n]+sorted(set(forms)-{n})[:48]

def verified_source_name(source,target):
    a,b=norm(source),norm(target)
    if a==b and a: return True
    bridge=verified_shared_source_name(source,target)
    if bridge is not None:
        return bridge
    fb,_,_=catalog()
    key=target_team_key(target)
    return bool(key and fb.get(a)==key)
