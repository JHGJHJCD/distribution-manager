# -*- coding: utf-8 -*-
"""Reachability history pulled from the Yemot server itself (v3.10/v3.11).

The app's own campaign reports (tzintuk_campaigns) only start at the day the
software was first used — but the line has been ringing people for years, and
Yemot keeps two things we can read:

* every campaign ever run (``GetTransactions`` lists them, ``GetCampaignStatus``
  still answers for old ones with the real dial time of each number and its
  redials);
* the folder enter/exit log (``Log/LogFolderEnterExit-YYYY-MM.ymgr``) — one
  line per extension visit, so every INCOMING call to the line, with the
  caller's number and the Israel-clock time. Monthly files since 2020.

v3.11 (user's decision 3/9/2026): the whole history since the line began —
not a rolling window. Incoming calls are stored AGGREGATED (phone → hour →
count, per month) so seven years fit in a small file and answer_stats stays
fast; a month is re-read only when its size on the server changed.

Cached locally in ``%APPDATA%\\ManhalHaluka\\yemot_history.json`` (the server
is the source of truth, so each computer pulls its own copy — no sync journal
traffic). Pure module: no Qt; the network goes through ``utils.yemot``.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

import database as db

CACHE_NAME = "yemot_history.json"
MAX_TX_PAGES = 500             # GetTransactions pages of 200 (safety cap)
_TX_TS = "%Y-%m-%d %H:%M:%S"
_LOG_RE = re.compile(r"^LogFolderEnterExit-(\d{4}-\d{2})\.ymgr$")

_memo = {"path": None, "mtime": None, "data": None}


def cache_path() -> str:
    return os.path.join(db._data_dir(), CACHE_NAME)


def _empty() -> dict:
    return {"campaigns": {}, "months": {}, "updated": "", "tx_done": False}


def _aggregate(rows: list) -> dict:
    """[[phone, 'YYYY-MM-DD HH:MM'], …] → {phone: {'HH': n}}."""
    hours = {}
    for row in rows or []:
        try:
            p, stamp = row[0], row[1]
            h = stamp[11:13]
            int(h)
        except (IndexError, TypeError, ValueError):
            continue
        if p:
            d = hours.setdefault(p, {})
            d[h] = d.get(h, 0) + 1
    return hours


def _normalize_month(m) -> dict:
    """Accept the v3.10 raw-rows shape and the aggregated shape."""
    if not isinstance(m, dict):
        return {"size": None, "calls": 0, "hours": {}}
    if "hours" not in m:
        rows = m.get("calls") if isinstance(m.get("calls"), list) else []
        return {"size": m.get("size"), "calls": len(rows), "hours": _aggregate(rows)}
    m.setdefault("size", None)
    m.setdefault("calls", sum(sum(v.values()) for v in m["hours"].values()))
    return m


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
    data["months"] = {k: _normalize_month(v) for k, v in (data.get("months") or {}).items()}
    data.setdefault("updated", "")
    data.setdefault("tx_done", False)
    _memo.update(path=path, mtime=mtime, data=data)
    return data


def save(data: dict):
    path = cache_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    _memo.update(path=None, mtime=None, data=None)


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


def available_months(yemot) -> dict:
    """{'2020-02': size, …} — every enter/exit log file on the server."""
    listing = yemot._call("GetIVR2Dir", {"path": "ivr2:/Log"})
    out = {}
    for f in listing.get("files") or []:
        m = _LOG_RE.match(str(f.get("name") or ""))
        if m and f.get("exists", True):
            try:
                out[m.group(1)] = int(f.get("size") or 0)
            except (TypeError, ValueError):
                out[m.group(1)] = None
    return out


def _tx_campaigns(yemot, progress) -> dict:
    """{campaignId: 'YYYY-MM-DD HH:MM:SS' (Israel)} for every campaign
    transaction on the account, paging GetTransactions to the end."""
    found = {}
    offset = 0
    for page in range(MAX_TX_PAGES):
        progress(f"קורא את רשימת הקמפיינים מהשרת… (עמוד {page + 1})")
        data = yemot._call("GetTransactions", {"limit": "200", "from": str(offset)})
        rows = data.get("transactions") or []
        if not rows:
            break
        for t in rows:
            cid = t.get("campaignId")
            if cid:
                found.setdefault(str(cid), str(t.get("transactionTime") or ""))
        if len(rows) < 200:
            break
        offset += len(rows)
    return found


def sync_from_server(progress=None, months: int | None = None) -> dict:
    """Pull what is missing from the server into the cache — the whole
    history. `months` (tests) limits to the newest N log months. Returns a
    summary: {'new_campaigns', 'months_fetched', 'errors', 'campaigns',
    'calls', 'months', 'since', 'updated'}. A failure on one item (NetFree
    content scan on a big log, a campaign the server forgot) is counted and
    skipped — the rest still lands."""
    from utils import yemot
    say = progress or (lambda _t: None)
    data = load()
    errors = 0

    # 1. campaigns
    try:
        wanted = _tx_campaigns(yemot, say)
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

    # 2. incoming calls — a month is read when missing or when its file grew
    say("קורא את רשימת קובצי היומן…")
    try:
        avail = available_months(yemot)
    except Exception:
        avail, errors = {}, errors + 1
    keys = sorted(avail)
    if months:
        keys = keys[-months:]
    months_fetched = 0
    for key in keys:
        cur = data["months"].get(key)
        if cur is not None and cur.get("size") is not None and cur["size"] == avail[key]:
            continue
        say(f"קורא את יומן השיחות של {key[5:]}/{key[:4]}…")
        try:
            raw = yemot._download(f"ivr2:/Log/LogFolderEnterExit-{key}.ymgr")
        except Exception:
            errors += 1
            continue
        rows = [] if (not raw or raw[:1] == b"{") else \
            parse_enter_exit(raw.decode("utf-8", errors="replace"))
        data["months"][key] = {"size": avail[key], "calls": len(rows),
                               "hours": _aggregate(rows)}
        months_fetched += 1
        if months_fetched % 6 == 0:
            save(data)
    data["updated"] = datetime.utcnow().isoformat() + "+00:00"
    save(data)
    s = summary(data)
    s.update(new_campaigns=new_campaigns, months_fetched=months_fetched, errors=errors)
    return s


def summary(data: dict | None = None) -> dict:
    data = data or load()
    months = sorted(data.get("months") or {})
    return {"campaigns": len(data.get("campaigns") or {}),
            "calls": sum(int((m or {}).get("calls") or 0)
                         for m in (data.get("months") or {}).values()),
            "months": months,
            "since": months[0] if months else "",
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
