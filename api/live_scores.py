from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import csv
import io
import json
import os
import re
import unicodedata

import requests

HKT = timezone(timedelta(hours=8))
FOTMOB = os.environ.get("FOTMOB_BASE_URL", "https://www.fotmob.com/api").rstrip("/")
BACKUP = os.environ.get("SPORTSCORE_BASE", "https://sportscore.com").rstrip("/")
HKJC_CSV = os.environ.get(
    "HKJC_CURRENT_CSV",
    "https://raw.githubusercontent.com/sargesticky-code/football-fast-tracker/main/data/hkjc_current.csv",
)
UA = "football-fast-tracker-live/1.0"
ENDED = ("ENDED", "MATCHENDED", "FT", "AET", "PEN", "CANCEL", "VOID", "ABANDON")


def clean(v):
    return "" if v is None else str(v).strip()


def norm(v):
    s = unicodedata.normalize("NFKD", clean(v))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"['’`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    # HKJC uses AM in age-group team names; providers commonly use U23.
    s = re.sub(r"\b(u ?23|under ?23|u ?22|u ?21|u ?20|u ?19|am)\b", " ", s)
    s = re.sub(r"\b(fc|cf|sc|afc|club|football|soccer)\b", " ", s)
    return " ".join(s.split())


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        short, long = min(len(a), len(b)), max(len(a), len(b))
        if short >= 4:
            return max(0.88, short / long)
    return SequenceMatcher(None, a, b).ratio()


def parse_dt(v):
    s = clean(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HKT)
        return dt.astimezone(HKT)
    except Exception:
        return None


def fetch_json(url, params=None):
    r = requests.get(
        url,
        params=params,
        headers={"Accept": "application/json", "User-Agent": UA},
        timeout=12,
    )
    r.raise_for_status()
    return r.json()


def hkjc_targets(now):
    r = requests.get(HKJC_CSV, headers={"User-Agent": UA}, timeout=12)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))
    out = []
    for row in rows:
        kick = parse_dt(row.get("kickoff_hkt"))
        if not kick:
            continue
        status = clean(row.get("status")).upper()
        ended = any(x in status for x in ENDED)
        in_play = clean(row.get("in_play")).lower() in ("1", "true", "yes")
        # Candidate window intentionally independent of HKJC live polling.
        if ended and not in_play:
            continue
        if not (now - timedelta(hours=4) <= kick <= now + timedelta(minutes=45)):
            continue
        out.append({
            "hkjc_event_id": clean(row.get("hkjc_event_id")),
            "kickoff_hkt": kick,
            "league": clean(row.get("tournament")),
            "home_en": clean(row.get("home_en")),
            "away_en": clean(row.get("away_en")),
            "corner_line_ref": clean(row.get("chl_line")),
            "corner_over_ref": clean(row.get("chl_over")),
            "corner_under_ref": clean(row.get("chl_under")),
        })
    return out


def score_pair(m):
    home = m.get("home") or {}
    away = m.get("away") or {}
    hs = clean(home.get("score"))
    aw = clean(away.get("score"))
    st = m.get("status") or {}
    if hs != "" and aw != "":
        return hs, aw
    ss = clean(st.get("scoreStr") or st.get("score"))
    z = re.search(r"(\d+)\s*[-:]\s*(\d+)", ss)
    return (z.group(1), z.group(2)) if z else ("", "")


def minute_from_status(st):
    if not isinstance(st, dict):
        return ""
    for k in ("minute", "elapsed", "time"):
        v = st.get(k)
        if v not in (None, ""):
            z = re.search(r"\d+(?:\+\d+)?", clean(v))
            if z:
                return z.group(0)
    live = st.get("liveTime")
    vals = live.values() if isinstance(live, dict) else [live]
    for v in vals:
        if v not in (None, ""):
            z = re.search(r"\d+(?:\+\d+)?", clean(v))
            if z:
                return z.group(0)
    z = re.search(r"\b\d+(?:\+\d+)?\b", clean(st.get("reason")))
    return z.group(0) if z else ""


def fotmob_headers():
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.fotmob.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }


def parse_nonnegative(v):
    if v in (None, ""):
        return None
    z = re.search(r"\d+(?:\.\d+)?", clean(v))
    if not z:
        return None
    n = float(z.group(0))
    return int(n) if n.is_integer() else n


def fetch_fotmob_corners(match_id):
    """Return live home/away/total corners from FotMob matchDetails.

    FotMob has used both flat and grouped stat layouts, so scan recursively
    instead of depending on one exact nesting shape.
    """
    if not match_id:
        return None
    r = requests.get(
        FOTMOB + "/data/matchDetails",
        params={"matchId": clean(match_id)},
        headers=fotmob_headers(),
        timeout=10,
    )
    r.raise_for_status()
    detail = r.json()
    stats_root = ((detail.get("content") or {}).get("stats") or {})

    def walk(node):
        if isinstance(node, dict):
            key = clean(node.get("key")).lower()
            title = clean(node.get("title")).lower()
            label = " ".join(x for x in (key, title) if x)
            vals = node.get("stats")
            if ("corner" in label) and isinstance(vals, list) and len(vals) >= 2:
                home = parse_nonnegative(vals[0])
                away = parse_nonnegative(vals[1])
                if home is not None and away is not None:
                    return {
                        "home_corners": home,
                        "away_corners": away,
                        "total_corners": home + away,
                    }
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found:
                    return found
        return None

    return walk(stats_root)


def corner_progress(total, line):
    if total in (None, "") or line in (None, ""):
        return {"corners_to_hi": "", "corner_progress": ""}
    try:
        total_n = int(float(total))
        line_n = float(line)
    except Exception:
        return {"corners_to_hi": "", "corner_progress": ""}
    target = int(line_n // 1) + 1
    need = max(0, target - total_n)
    status = "HI HIT" if need == 0 else f"+{need}"
    return {
        "corners_to_hi": need,
        "corner_progress": f"{total_n}/{line_n:g} · {status}",
    }


def primary_matches():
    """Self-hosted Football Live API logic using FotMob directly."""
    now = datetime.now(HKT)
    dates = [now.strftime("%Y%m%d")]
    if now.hour < 3:
        dates.append((now - timedelta(days=1)).strftime("%Y%m%d"))

    headers = fotmob_headers()
    out = []
    seen = set()
    for ymd in dates:
        r = requests.get(
            FOTMOB + "/data/matches",
            params={"date": ymd, "timezone": "Asia/Hong_Kong", "ccode3": "HKG"},
            headers=headers,
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        for lg in data.get("leagues") or []:
            for m in lg.get("matches") or []:
                st = m.get("status") or {}
                is_live = (
                    st.get("ongoing") is True
                    or (
                        st.get("started") is True
                        and st.get("finished") is False
                        and st.get("cancelled") is not True
                    )
                )
                if not is_live:
                    continue
                mid = clean(m.get("id"))
                if mid and mid in seen:
                    continue
                if mid:
                    seen.add(mid)
                h = m.get("home") or {}
                a = m.get("away") or {}
                hs, aw = score_pair(m)
                out.append({
                    "source": "FOOTBALL_LIVE_API_SELF_HOSTED",
                    "source_match_id": mid,
                    "home": clean(h.get("name")),
                    "away": clean(a.get("name")),
                    "kickoff": parse_dt(st.get("utcTime") or m.get("utcTime")),
                    "home_score": hs,
                    "away_score": aw,
                    "minute": minute_from_status(st),
                    "status": clean(st.get("reason")) or "LIVE",
                    "updated_at": now.isoformat(timespec="seconds"),
                })
    return out


def get_first(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return ""


def team_name(v):
    if isinstance(v, dict):
        return clean(get_first(v, ("name", "title", "shortName", "short_name")))
    return clean(v)


def side_score(m, side):
    direct = get_first(m, (
        f"{side}_score", f"{side}Score", f"score_{side}",
        "homeScore" if side == "home" else "awayScore",
    ))
    if direct not in (None, ""):
        return clean(direct)
    s = m.get("score")
    if isinstance(s, dict):
        v = get_first(s, (side, f"{side}Score"))
        if isinstance(v, dict):
            v = get_first(v, ("current", "display", "total", "score"))
        return clean(v)
    if isinstance(s, str):
        z = re.search(r"(\d+)\s*[-:]\s*(\d+)", s)
        if z:
            return z.group(1 if side == "home" else 2)
    return ""


def backup_matches():
    body = fetch_json(
        BACKUP + "/api/widget/matches/",
        {"sport": "football", "limit": 50},
    )
    raw = body.get("matches") if isinstance(body, dict) else []
    if raw is None and isinstance(body, dict):
        raw = body.get("data") or []
    if isinstance(raw, dict):
        raw = raw.get("matches") or raw.get("items") or []
    out = []
    for m in raw if isinstance(raw, list) else []:
        if not isinstance(m, dict):
            continue
        hv = get_first(m, ("home", "homeTeam", "home_team", "team1"))
        av = get_first(m, ("away", "awayTeam", "away_team", "team2"))
        home, away = team_name(hv), team_name(av)
        if not home or not away:
            continue
        st = get_first(m, ("status", "state", "matchStatus", "match_status"))
        if isinstance(st, dict):
            status = clean(get_first(st, ("name", "short", "type", "description", "status")))
            minute = clean(get_first(st, ("minute", "elapsed", "clock")))
        else:
            status = clean(st)
            minute = clean(get_first(m, ("minute", "elapsed", "clock")))
        out.append({
            "source": "SPORTSCORE",
            "source_match_id": clean(get_first(m, ("id", "match_id", "matchId", "slug"))),
            "home": home,
            "away": away,
            "kickoff": parse_dt(get_first(m, ("kickoff", "startTime", "start_time", "date", "utcTime"))),
            "home_score": side_score(m, "home"),
            "away_score": side_score(m, "away"),
            "minute": minute,
            "status": status or "LIVE",
            "updated_at": clean(get_first(m, ("updatedAt", "updated_at", "lastUpdated"))),
        })
    return out


def best_match(target, candidates):
    ranked = []
    for m in candidates:
        hs = sim(target["home_en"], m["home"])
        aws = sim(target["away_en"], m["away"])
        if min(hs, aws) < 0.58:
            continue
        ts = 0.75
        if m.get("kickoff"):
            delta = abs((m["kickoff"] - target["kickoff_hkt"]).total_seconds()) / 60
            if delta > 120:
                continue
            ts = max(0.0, 1 - delta / 180)
        score = 0.42 * hs + 0.42 * aws + 0.16 * ts
        ranked.append((score, m))
    if not ranked:
        return None, 0
    ranked.sort(key=lambda x: x[0], reverse=True)
    best = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else 0
    if best[0] < 0.74:
        return None, best[0]
    if best[0] < 0.90 and second and best[0] - second < 0.06:
        return None, best[0]
    return best[1], best[0]


def collect():
    now = datetime.now(HKT)
    targets = hkjc_targets(now)
    health = {"primary": "NOT_CALLED", "backup": "NOT_CALLED"}
    try:
        primary = primary_matches()
        health["primary"] = "OK"
    except Exception as e:
        primary = []
        health["primary"] = "ERROR:" + type(e).__name__

    backup = None
    rows = []
    for t in targets:
        m, conf = best_match(t, primary)
        if m is None:
            if backup is None:
                try:
                    backup = backup_matches()
                    health["backup"] = "OK"
                except Exception as e:
                    backup = []
                    health["backup"] = "ERROR:" + type(e).__name__
            m, conf = best_match(t, backup)

        if m is None:
            continue
        hs, aw = clean(m["home_score"]), clean(m["away_score"])
        live_corners = None
        if m.get("source") == "FOOTBALL_LIVE_API_SELF_HOSTED":
            try:
                live_corners = fetch_fotmob_corners(m.get("source_match_id"))
            except Exception:
                live_corners = None

        hc = live_corners.get("home_corners") if live_corners else ""
        ac = live_corners.get("away_corners") if live_corners else ""
        tc = live_corners.get("total_corners") if live_corners else ""
        cp = corner_progress(tc, t.get("corner_line_ref"))

        rows.append({
            "hkjc_event_id": t["hkjc_event_id"],
            "kickoff_hkt": t["kickoff_hkt"].isoformat(timespec="minutes"),
            "league": t["league"],
            "home_en": t["home_en"],
            "away_en": t["away_en"],
            "live_score": f"{hs}-{aw}" if hs != "" and aw != "" else "",
            "home_score": hs,
            "away_score": aw,
            "minute": clean(m["minute"]),
            "match_status": clean(m["status"]),
            "source": m["source"],
            "source_match_id": m["source_match_id"],
            "source_home": m["home"],
            "source_away": m["away"],
            "match_confidence": round(conf, 3),
            "source_updated_at": m["updated_at"],
            "home_corners": hc,
            "away_corners": ac,
            "total_corners": tc,
            "corner_line_ref": t.get("corner_line_ref", ""),
            "corners_to_hi": cp["corners_to_hi"],
            "corner_progress": cp["corner_progress"],
        })
    rows.sort(key=lambda r: r["kickoff_hkt"])
    return {
        "updatedAt": now.isoformat(timespec="seconds"),
        "health": health,
        "targetCount": len(targets),
        "matchedCount": len(rows),
        "matches": rows,
        "attribution": {
            "SportScore": "Powered by SportScore — https://sportscore.com/"
        },
    }


def as_csv(payload):
    fields = [
        "updatedAt", "hkjc_event_id", "kickoff_hkt", "league", "home_en", "away_en",
        "live_score", "home_score", "away_score", "minute", "match_status",
        "source", "source_match_id", "source_home", "source_away",
        "match_confidence", "source_updated_at",
        "home_corners", "away_corners", "total_corners",
        "corner_line_ref", "corners_to_hi", "corner_progress",
    ]
    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=fields)
    w.writeheader()
    for row in payload["matches"]:
        item = {"updatedAt": payload["updatedAt"], **row}
        w.writerow({k: item.get(k, "") for k in fields})
    return s.getvalue()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        fmt = clean((qs.get("format") or ["json"])[0]).lower()
        try:
            payload = collect()
            if fmt == "csv":
                body = as_csv(payload).encode("utf-8-sig")
                ctype = "text/csv; charset=utf-8"
            else:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                ctype = "application/json; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "s-maxage=15, stale-while-revalidate=15")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"ok": False, "error": type(e).__name__}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
