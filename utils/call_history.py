# -*- coding: utf-8 -*-
"""Reachability history pulled from the Yemot server itself (v3.10).

The app's own campaign reports (tzintuk_campaigns) only start at the day the
software was first used — but the line has been ringing people for years, and
Yemot keeps two things we can read:

* every campaign ever run (``GetTransactions`` lists them, ``GetCampaignStatus``
  still answers for old ones with the real dial time of each number and its
  redials);
* the folder enter/exit log (``Log/LogFolderEnterExit-YYYY-MM.ymgr``) — one
  line per extension visit, so every INCOMING call to the line, with the
  caller's number and the Israel-clock time.

Both are cached locally in ``%APPDATA%\\ManhalHaluka\\yemot_history.json``
(the server is the source of truth, so each computer pulls its own copy — no
sync journal traffic). ``yemot.answer_stats`` merges this cache with the app's
own reports. Pure module: no Qt; the network goes through ``utils.yemot``.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

import database as db

CACHE_NAME = "yemot_history.json"
DEFAULT_MONTHS = 12            # how far back the first pull goes
MAX_TX_PAGES = 40              # GetTransactions pages of 200 (safety cap)
_TX_TS = "%Y-%m-%d %H:%M:%S"

_memo = {"path": None, "mtime": None, "data": None}


def cache_path() -> str:
    return os.path.join(db._data_dir(), CACHE_NAME)


def _empty() -> dict:
    return {"campaigns": {}, "months": {}, "updated": ""}


def load() -> dict:
    """The cached history (memoised on the file's mtime — answer_stats is
    called on every refresh)."""
    path = cache_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return _empty()
    if _memo["path"] == path and _memo["mtime"] == mtime and _memo["data"] is not None:
        return _memo["data"]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("campaigns", {})
    data.setdefault("months", {})
    data.setdefault("updated", "")
    _memo.update(path=path, mtime=mtime, data=data)
    return data


def save(data: dict):
    path = cache_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    _memo.update(path=None, mtime=None, data=None)


def month_keys(months: int = DEFAULT_MONTHS, today: date | None = None) -> list:
    """['2025-10', …, '2026-09'] — the last `months` months, oldest first,
    the current month last."""
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(max(1, months)):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def parse_enter_exit(text: str) -> list:
    """LogFolderEnterExit text → [[phone, 'YYYY-MM-DD HH:MM'], …] — ONE row per
    incoming call (the first line of each CallId; the log has a line per
    extension visited). Times are the Israel clock as written by the server."""
    from utils.yemot import normalize_phone
    seen = set()
    out = []
    for raw in (text or "").splitlines():
        kv = {}
        for part in raw.strip().split("%"):
            if "#" in part:
                k, v = part.split("#", 1)
                kv[k.strip()] = v.strip()
        call_id = kv.get("CallId") or ""
        phone = normalize_phone(kv.get("Phone"))
        d, t = kv.get("EnterDate") or "", kv.get("EnterTime") or ""
        if not phone or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", d) \
                or not re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", t):
            continue
        key = call_id or (phone, d, t)
        if key in seen:
            continue
        seen.add(key)
        dd, mm, yy = d.split("/")
        out.append([phone, f"{yy}-{mm}-{dd} {t[:5]}"])
    return out


def _tx_campaigns(yemot, cutoff: datetime) -> dict:
    """{campaignId: 'YYYY-MM-DD HH:MM:SS' (Israel)} for every campaign
    transaction newer than `cutoff`, paging GetTransactions."""
    found = {}
    offset = 0
    for _ in range(MAX_TX_PAGES):
        data = yemot._call("GetTransactions", {"limit": "200", "from": str(offset)})
        rows = data.get("transactions") or []
        if not rows:
            break
        oldest = None
        for t in rows:
            when = str(t.get("transactionTime") or "")
            try:
                ts = datetime.strptime(when[:19], _TX_TS)
            except ValueError:
                continue
            oldest = ts if oldest is None or ts < oldest else oldest
            cid = t.get("campaignId")
            if cid and ts >= cutoff:
                found.setdefault(str(cid), when)
        if oldest is not None and oldest < cutoff:
            break
        offset += len(rows)
    return found


def sync_from_server(months: int = DEFAULT_MONTHS, progress=None,
                     today: date | None = None) -> dict:
    """Pull what is missing from the server into the cache. Returns a summary:
    {'new_campaigns', 'months_fetched', 'errors', 'campaigns', 'calls'}.
    A failure on one item (NetFree content scan on a big log, a campaign the
    server forgot) is counted and skipped — the rest still lands."""
    from utils import yemot
    say = progress or (lambda _t: None)
    data = load()
    keys = month_keys(months, today)
    cutoff = datetime.strptime(keys[0] + "-01 00:00:00", _TX_TS)
    errors = 0

    # 1. campaigns
    say("קורא את רשימת הקמפיינים מהשרת…")
    try:
        wanted = _tx_campaigns(yemot, cutoff)
    except Exception:
        wanted, errors = {}, errors + 1
    todo = [cid for cid in wanted if cid not in data["campaigns"]]
    new_campaigns = 0
    for i, cid in enumerate(todo, 1):
        say(f"מושך קמפיין {i} מתוך {len(todo)}…")
        try:
            st = yemot.get_campaign_status(cid)
        except Exception:
            errors += 1
            continue
        if not st.get("finished") and st.get("pending"):
            continue                      # still running — next time
        data["campaigns"][cid] = {
            "at": yemot._israel_str_to_utc_iso(wanted[cid]),
            "entries": [{k: e.get(k) for k in
                         ("phone", "status", "ok", "failed", "at", "duration", "redials")}
                        for e in st.get("entries") or []],
        }
        new_campaigns += 1
        if new_campaigns % 10 == 0:
            save(data)

    # 2. incoming calls — the current month is always re-read (it grows)
    current = keys[-1]
    months_fetched = 0
    for key in keys:
        if key in data["months"] and key != current:
            continue
        say(f"קורא את יומן השיחות של {key[5:]}/{key[:4]}…")
        try:
            raw = yemot._download(f"ivr2:/Log/LogFolderEnterExit-{key}.ymgr")
        except Exception:
            errors += 1
            continue
        if not raw or raw[:1] == b"{":
            calls = []                    # no such month on the server
        else:
            calls = parse_enter_exit(raw.decode("utf-8", errors="replace"))
        data["months"][key] = {"calls": calls,
                               "fetched": datetime.utcnow().isoformat() + "+00:00"}
        months_fetched += 1
    data["updated"] = datetime.utcnow().isoformat() + "+00:00"
    save(data)
    s = summary(data)
    s.update(new_campaigns=new_campaigns, months_fetched=months_fetched, errors=errors)
    return s


def summary(data: dict | None = None) -> dict:
    data = data or load()
    return {"campaigns": len(data.get("campaigns") or {}),
            "calls": sum(len((m or {}).get("calls") or [])
                         for m in (data.get("months") or {}).values()),
            "months": sorted(data.get("months") or {}),
            "updated": data.get("updated") or ""}


def is_stale(hours: float = 24.0, data: dict | None = None) -> bool:
    """True when the cache was never pulled or is older than `hours`."""
    data = data or load()
    upd = data.get("updated") or ""
    if not upd:
        return True
    try:
        dt = datetime.fromisoformat(upd)
    except ValueError:
        return True
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.utcnow()
    return (now - dt).total_seconds() > hours * 3600
