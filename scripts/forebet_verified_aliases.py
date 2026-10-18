"""Locally snapshotted, source-verified Forebet aliases. Never fuzzy match.

Only existing VERIFIED registry aliases, >=0.95 confidence and a unique
team_key are eligible. Runtime reads a 54KB repository JSON file: no new
Supabase request, source scrape, database table or scheduled task.
"""
import json
import re
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


@lru_cache(maxsize=1)
def native_verified_catalog():
    """One-time verified native Flashscore identities; no daily DB lookup.

    This separate snapshot must remain uniquely source-backed and must never
    include 30% fuzzy, owner-assumed, or provisional Forebet pairings.
    """
    data=json.loads((Path(__file__).resolve().parent.parent/
        "data/forebet_native_strict_aliases_20261018.json").read_text(encoding="utf-8"))
    if (data.get("snapshot_type")!="FOREBET_FLASHSCORE_NATIVE_EXACT_EVENT_ALIASES_V1"
        or data.get("policy")!="STRICT_SOURCE_EVENT_AND_FS_NATIVE_TEAM_ID_UNIQUE_NO_PROVISIONAL"
        or data.get("method")!="FOREBET_STRICT_TWO_TEAM_EXACT_FIXTURE_SOURCE"):
        raise ValueError("FOREBET_NATIVE_ALIASES_PROVENANCE_INVALID")
    rows=data.get("rows")
    if not isinstance(rows,list) or not 200<=len(rows)<=400:
        raise ValueError("FOREBET_NATIVE_ALIASES_COVERAGE_INVALID")
    source_ids,target_ids,forms={},{},{}
    for r in rows:
        if not isinstance(r,dict): raise ValueError("FOREBET_NATIVE_ALIAS_ROW_INVALID")
        sn=r.get("source_name")
        cn=r.get("flashscore_name")
        key=r.get("team_key")
        url=r.get("source_url")
        fid=r.get("fixture_id")
        if (not isinstance(sn,str) or not isinstance(cn,str)
            or not isinstance(key,str) or not re.fullmatch(r"FS_TEAM:[A-Za-z0-9]{6,16}",key)
            or not isinstance(url,str)
            or not re.fullmatch(r"https://www\\.forebet\\.com/en/football/matches/[^/?#]+-\\d{5,12}",url)
            or not isinstance(fid,str)
            or not re.fullmatch(r"FS:[A-Za-z0-9_-]{5,32}",fid)):
            raise ValueError("FOREBET_NATIVE_ALIAS_EVIDENCE_INVALID")
        src,tgt=norm(sn),norm(cn)
        if not src or not tgt: raise ValueError("FOREBET_NATIVE_ALIAS_EMPTY_NAME")
        if (src in source_ids and source_ids[src]!=key
            or tgt in target_ids and target_ids[tgt]!=key):
            raise ValueError("FOREBET_NATIVE_ALIAS_TEAM_CONFLICT")
        source_ids[src]=key
        target_ids[tgt]=key
        forms.setdefault(key,set()).add(src)
    return source_ids,target_ids,{k:sorted(v) for k,v in forms.items()}


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
    # Native source-backed forms take priority over legacy catalogue extras.
    _,native_targets,native_forms=native_verified_catalog()
    native_key=native_targets.get(n)
    forms=[n]+(native_forms.get(native_key,[]) if native_key else [])
    forms.extend(by_key.get(key,[]) if key else [])
    fs,fb,shared=shared_verified_catalog()
    verified_key=fs.get(n)
    if verified_key:
        forms.extend(shared.get(verified_key,[]))
    return [n]+sorted(set(forms)-{n})[:48]

def verified_source_name(source,target):
    a,b=norm(source),norm(target)
    if a==b and a: return True
    native_source,native_target,_=native_verified_catalog()
    if a in native_source and b in native_target:
        return native_source[a]==native_target[b]
    bridge=verified_shared_source_name(source,target)
    if bridge is not None:
        return bridge
    fb,_,_=catalog()
    key=target_team_key(target)
    return bool(key and fb.get(a)==key)
