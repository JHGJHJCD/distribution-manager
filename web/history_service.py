# -*- coding: utf-8 -*-
"""Stage 4 — the history screen: every round that has passed and who was in it, and "when
did so-and-so receive". Plain functions over a connection and the current time (no web
framework), like web/service.py.

READING ONLY. The past is fixed: nothing here changes a history row. (As on every screen, a
week or a holiday event whose day has passed is first written to the history as it was
computed — web/service.py: roll_forward.)

Names only leave the store here: no phones, no notes, no other detail of a card or of a
history row.

Three kinds of rows live in the history:
  * a ROUND — a `batches` row with the people who were in it: a week / a holiday event the
    site closed, or a distribution that was recorded in the desktop program;
  * OLD RECORDS — history rows that belong to no round (they were recorded one by one, long
    ago). They are shown apart, by their date;
  * a row may say "did not come" (`received=0`, from the desktop program). The site itself
    never writes one.
"""
from datetime import datetime

from . import planner, service, store
from .engine import holidays
from .service import Refused

PAGE = 30                         # rounds on one page of the screen
MAX_PAGE = 200
KIND_REGULAR, KIND_HOLIDAY, KIND_BONUS = "regular", "holiday", "bonus"

# "the latest first": real dates from the newest down, and after them — never before — what
# carries a date that is not a date (it cannot be placed in time)
def _latest_first(column: str) -> str:
    return f"({column} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]') DESC, {column} DESC"


# a history row belongs to no round when it names none, or names one that is not there
_NO_ROUND = ("(h.batch_guid IS NULL OR h.batch_guid='' "
             "OR NOT EXISTS (SELECT 1 FROM batches b WHERE b.guid=h.batch_guid))")


def round_kind(code) -> str:
    """What kind of round a holiday code says: a regular one, a holiday one, or a bonus."""
    code = (str(code or "")).strip()
    if not code:
        return KIND_REGULAR
    return KIND_BONUS if code == holidays.BONUS else KIND_HOLIDAY


def _day(text):
    """(the date as it is shown, the day's name) — ('' , '') for a date that is not a date."""
    d = planner.to_date(text) if planner.valid_iso(text) else None
    return (d.isoformat(), service.day_name(d)) if d else ("", "")


def _round(b, got: int, absent: int) -> dict:
    code = (b["holiday"] or "").strip()
    iso, day = _day(b["dist_date"])
    return {
        "batch": b["guid"], "date": iso, "day": day, "raw_date": "" if iso else (b["dist_date"] or ""),
        "name": (b["dist_name"] or "").strip(), "kind": round_kind(code), "label": holidays.dist_label(code),
        "received": got, "absent": absent, "from_site": b["source"] == "web",
    }


def _clamp(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def overview(conn, now: datetime, offset=0, limit=PAGE, db_path: str = None) -> dict:
    """The rounds that have passed, the latest first — one page of them, with how many there
    are in all (so the screen can always say that there are more) — and the old records that
    belong to no round, by date."""
    service.roll_forward(conn, now, db_path)
    offset, limit = _clamp(offset, 0, 10 ** 7, 0), _clamp(limit, 1, MAX_PAGE, PAGE)
    total = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
    rounds = [_round(b, b["got"] or 0, b["absent"] or 0) for b in conn.execute(
        "SELECT b.guid, b.dist_name, b.dist_date, b.holiday, b.source, "
        "       SUM(CASE WHEN h.received=1 THEN 1 ELSE 0 END) AS got, "
        "       SUM(CASE WHEN h.received=0 THEN 1 ELSE 0 END) AS absent "
        "FROM batches b LEFT JOIN history h ON h.batch_guid=b.guid "
        f"GROUP BY b.guid ORDER BY {_latest_first('b.dist_date')}, b.created_at DESC, b.guid DESC LIMIT ? OFFSET ?",
        (limit, offset))]
    old = []
    for r in conn.execute(
            "SELECT h.dist_date AS d, SUM(CASE WHEN h.received=1 THEN 1 ELSE 0 END) AS got, "
            "       SUM(CASE WHEN h.received=0 THEN 1 ELSE 0 END) AS absent "
            f"FROM history h WHERE {_NO_ROUND} GROUP BY h.dist_date ORDER BY {_latest_first('h.dist_date')}"):
        iso, day = _day(r["d"])
        old.append({"key": r["d"] or "", "date": iso, "day": day, "received": r["got"] or 0,
                    "absent": r["absent"] or 0})
    return {"rounds": rounds, "total": total, "offset": offset, "more": offset + len(rounds) < total,
            "old": old, "old_rows": sum(o["received"] + o["absent"] for o in old),
            "rows": conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"]}


# ── who was in a round ────────────────────────────────────────────────────────
def _cards(conn) -> dict:
    """{guid: the card} — for today's name and kind of everybody in a list."""
    return {r["guid"]: r for r in store.load_recipients(conn)}


def _person(guid, written_name: str, cards: dict) -> dict:
    """One name in a list of the past: the card's name today (a card that was renamed is
    found under its new name), or the name that was written when the card is gone."""
    card = cards.get(guid) if guid else None
    if card is None:
        return {"guid": "", "name": (written_name or "").strip() or "כרטיס שנמחק", "kind": planner.KIND_OTHER, "freq": ""}
    kind = (planner.participation(card) if planner.is_active(card) else "") or planner.KIND_OTHER
    return {"guid": card["guid"], "name": card.get("full_name") or "", "kind": kind,
            "freq": (card.get("frequency") or "").strip()}


def _split(rows, cards: dict) -> tuple:
    got, absent = [], []
    for r in rows:
        (got if r["received"] else absent).append(_person(r["recipient_guid"], r["recipient_name"], cards))
    by_name = lambda p: p["name"]
    return sorted(got, key=by_name), sorted(absent, key=by_name)


def round_detail(conn, now: datetime, batch: str, db_path: str = None) -> dict:
    """Everybody who was in one round: who received, who was recorded as not coming, and —
    for a round the site closed — who waited on the reserve."""
    service.roll_forward(conn, now, db_path)
    b = conn.execute("SELECT guid, dist_name, dist_date, holiday, source FROM batches WHERE guid=?", (batch,)).fetchone()
    if b is None:
        raise Refused("החלוקה הזו לא נמצאה בהיסטוריה")
    cards = _cards(conn)
    got, absent = _split(conn.execute(
        "SELECT recipient_guid, recipient_name, received FROM history WHERE batch_guid=? ORDER BY id", (batch,)), cards)
    reserve = []
    for table, key in (("weeks", "week_wed"), ("events", "guid")):
        owner = conn.execute(f"SELECT {key} AS k FROM {table} WHERE batch_guid=?", (batch,)).fetchone()
        if owner is not None:
            members = "week_members" if table == "weeks" else "event_members"
            column = "week_wed" if table == "weeks" else "event_guid"
            reserve = [_person(m["recipient_guid"], "", cards) for m in conn.execute(
                f"SELECT recipient_guid FROM {members} WHERE {column}=? AND role='reserve' ORDER BY position",
                (owner["k"],))]
            break
    d = _round(b, len(got), len(absent))
    d.update(people=got, absent_people=absent, reserve=reserve)
    return d


def old_day(conn, now: datetime, key: str, db_path: str = None) -> dict:
    """The old records of one date (rows that belong to no round), names only."""
    service.roll_forward(conn, now, db_path)
    cards = _cards(conn)
    got, absent = _split(conn.execute(
        "SELECT h.recipient_guid, h.recipient_name, h.received FROM history h "
        f"WHERE h.dist_date=? AND {_NO_ROUND} ORDER BY h.id", (key,)), cards)
    if not got and not absent:
        raise Refused("אין רישומים ישנים בתאריך הזה")
    iso, day = _day(key)
    return {"key": key, "date": iso, "day": day, "people": got, "absent_people": absent}


# ── when did one person receive ───────────────────────────────────────────────
def person(conn, now: datetime, guid: str, db_path: str = None) -> dict:
    """Everything the history holds about one card, the latest first — every row, never a
    part of them: the day, the round it belongs to, and whether the row says "received"."""
    service.roll_forward(conn, now, db_path)
    card = store.get_recipient(conn, guid)
    if card is None:
        raise Refused("הכרטיס לא נמצא")
    rows = []
    for r in conn.execute(
            "SELECT h.dist_date, h.received, h.holiday, h.batch_guid, b.guid AS round, b.dist_name, "
            "       b.holiday AS round_holiday FROM history h LEFT JOIN batches b ON b.guid=h.batch_guid "
            f"WHERE h.recipient_guid=? ORDER BY {_latest_first('h.dist_date')}, h.id DESC", (guid,)):
        code = (r["holiday"] or r["round_holiday"] or "").strip()
        iso, day = _day(r["dist_date"])
        rows.append({"date": iso, "day": day, "raw_date": "" if iso else (r["dist_date"] or ""),
                     "received": bool(r["received"]), "kind": round_kind(code), "label": holidays.dist_label(code),
                     "name": (r["dist_name"] or "").strip(), "batch": r["round"] or ""})
    got = [r for r in rows if r["received"]]
    who = _person(guid, "", {guid: card})
    who.update(status=(card.get("status") or "").strip(), active=planner.is_active(card), rows=rows,
               received=len(got), absent=len(rows) - len(got),
               regular=sum(1 for r in got if r["kind"] == KIND_REGULAR),
               extra=sum(1 for r in got if r["kind"] != KIND_REGULAR),
               last=next((r["date"] for r in got if r["date"]), ""))
    return who
