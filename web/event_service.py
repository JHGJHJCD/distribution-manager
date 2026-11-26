# -*- coding: utf-8 -*-
"""Stage 4 — holiday events: the events that are ahead, one event in full, setting one up
and changing it, what the manager sets by hand for it, and its paper / Excel list. Plain
functions over a connection and the current time (no web framework), like web/service.py.

A holiday event is a round of its own that the manager sets up: a date, a holiday, a number
of portions and an optional filter. Like a coming week, its list is never stored while it
is ahead — it is computed each time (web/planner.py: plan_event, on the same time line as
the weeks). At 06:00 on the morning after its day it becomes history as it was computed
(web/service.py: _roll), and from then on it cannot be changed.

Names only leave the store here; phones go out only on the paper sheet and in the Excel
file, exactly as for a week.
"""
from datetime import date, datetime, timedelta

from . import config, planner, service, store
from .engine import holidays, selection
from .service import Refused

MAX_AHEAD_DAYS = 2 * 366          # an event further ahead than this is a typing mistake
_PASSED = "החלוקה הזו כבר עברה, ואי אפשר לשנות אותה"
_NOT_FOUND = "החלוקה לא נמצאה (אולי נמחקה בינתיים)"


def holiday_choices() -> list:
    """What an event can be for: everybody marked "נתמך חגים", or one named holiday."""
    return ([{"code": selection.HOLIDAY_ANY, "label": "כל נתמכי החגים"}]
            + [{"code": h, "label": h} for h in holidays.HOLIDAYS])


def filter_fields() -> list:
    return [{"field": f, "label": label} for f, label in selection.FILTER_FIELDS]


# ── reading ───────────────────────────────────────────────────────────────────
def _summary(p: dict, ctx: dict) -> dict:
    """An event that is ahead, in numbers (no names)."""
    return {
        "guid": p["guid"], "date": p["date"].isoformat(), "day": service.day_name(p["date"]),
        "holiday": p["holiday"], "name": holidays.dist_label(p["holiday"]),
        "portions": p["portions"], "reserve": p["reserve"], "criteria": p["criteria"], "balance": p["balance"],
        "marked": p["marked"], "eligible": p["eligible"], "missing": p["missing"], "unmarked": p["unmarked"],
        "main_count": len(p["main"]), "reserve_count": len(p["reserve_list"]),
        "left_out": sum(1 for e in p["out"] if e.get("group") in (planner.OUT_EV_CUT, planner.OUT_NO_PORTIONS)),
        "cut": p["cut"], "empty_portions": p["empty_portions"], "warnings": p["warnings"],
        "manual_count": len(next((e["manual"] for e in ctx["events"] if e["guid"] == p["guid"]), {})),
        "print": service.since_print(ctx["event_prints"].get(p["guid"]), [e["guid"] for e in p["main"]]),
    }


def _laid_out(conn, now: datetime, only: str = None):
    """The events that are ahead, laid out on the time line together with the weeks before
    them (their lists depend on those weeks). Returns (plans, context)."""
    ctx = service._context(conn, now)
    start = service.first_open_week(conn, now)
    days = [e["date"] for e in ctx["events"] if only is None or e["guid"] == only]
    weeks = max((planner.weeks_through(start, d) for d in days), default=0)
    if weeks > config.MAX_WEEKS:
        raise Refused("התאריך של החלוקה רחוק מדי")
    return service._timeline(ctx, start, weeks)["events"], ctx


def overview(conn, now: datetime, db_path: str = None) -> dict:
    """The holiday screen: the events that are ahead (in numbers), the ones that passed,
    and what a new event can be set to."""
    service.roll_forward(conn, now, db_path)
    plans, ctx = _laid_out(conn, now)
    past = [{"guid": e["guid"], "date": e["date"].isoformat(), "day": service.day_name(e["date"]),
             "name": holidays.dist_label(e["holiday"]), "main_count": e["main_count"] or 0,
             "batch": e["batch_guid"] or ""}
            for e in store.load_events(conn, open_only=False) if e["closed_at"]]
    past.sort(key=lambda e: e["date"], reverse=True)
    first = service.open_day(now)
    # taken away, and its day has not passed: it can still be brought back
    deleted = [{"guid": e["guid"], "date": e["date"].isoformat(), "day": service.day_name(e["date"]),
                "name": holidays.dist_label(e["holiday"]), "portions": e["portions"]}
               for e in store.deleted_events(conn) if e["date"] >= first]
    return {"first_day": first.isoformat(),
            "open": [_summary(p, ctx) for p in plans], "past": past, "deleted": deleted,
            "holidays": holiday_choices(), "filter": filter_fields(),
            "defaults": {"reserve": ctx["reserve"], "cooldown_weeks": ctx["cooldown"]}}


def detail(conn, now: datetime, guid: str, db_path: str = None) -> dict:
    """One event in full: who receives, the reserve, and who is outside it — each with the
    reason in a sentence. An event that has passed is shown as it was written."""
    service.roll_forward(conn, now, db_path)
    event = _known(conn, guid)
    if event["closed_at"]:
        return _closed(conn, event)
    plans, ctx = _laid_out(conn, now, only=guid)
    plan = next((p for p in plans if p["guid"] == guid), None)
    if plan is None:
        raise Refused(_NOT_FOUND)
    d = _summary(plan, ctx)
    names = {r["guid"]: r.get("full_name") or "" for r in ctx["recipients"]}
    d.update(closed=False, communities=plan["communities"], main=service._public(plan["main"]),
             reserve_list=service._public(plan["reserve_list"]), out=service._public(plan["out"]),
             print=service.since_print(ctx["event_prints"].get(guid), [e["guid"] for e in plan["main"]], names),
             holidays=holiday_choices(), filter=filter_fields(), first_day=service.open_day(now).isoformat(),
             cooldown_weeks=ctx["cooldown"])
    return d


def _closed(conn, event: dict) -> dict:
    """An event that is already history: the lists as they were written, names only."""
    names = {r["guid"]: r["full_name"] or "" for r in conn.execute("SELECT guid, full_name FROM recipients")}
    written = {r["recipient_guid"]: r["recipient_name"] or "" for r in conn.execute(
        "SELECT recipient_guid, recipient_name FROM history WHERE batch_guid=?", (event["batch_guid"] or "",))}
    lists = {"main": [], "reserve": []}
    for m in conn.execute("SELECT recipient_guid, role, kind, why FROM event_members WHERE event_guid=? "
                          "ORDER BY position", (event["guid"],)):
        g = m["recipient_guid"]
        lists.setdefault(m["role"], []).append({
            "guid": g, "name": names.get(g) or written.get(g) or "כרטיס שנמחק", "kind": m["kind"],
            "freq": "", "role": m["role"], "why": m["why"]})
    return {"closed": True, "guid": event["guid"], "date": event["date"].isoformat(),
            "day": service.day_name(event["date"]), "holiday": event["holiday"],
            "name": holidays.dist_label(event["holiday"]), "portions": event["portions"],
            "reserve": event["reserve"], "criteria": event["criteria"], "balance": event["balance"],
            "main": lists["main"], "reserve_list": lists["reserve"], "out": [],
            "main_count": len(lists["main"]), "reserve_count": len(lists["reserve"]),
            "batch": event["batch_guid"] or "", "warnings": []}


def _known(conn, guid: str) -> dict:
    """The event, or a refusal: one that was taken away is not there until it is brought back."""
    event = store.get_event(conn, guid)
    if event is None or event["deleted_at"]:
        raise Refused(_NOT_FOUND)
    return event


# ── setting an event up, changing it, taking it away ──────────────────────────
def _whole(value, what: str) -> int:
    if not (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= service.MAX_PORTIONS):
        raise Refused(f"{what}: צריך מספר שלם בין 0 ל-{service.MAX_PORTIONS}")
    return value


def _bound(value, label: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) > 1e9:
        raise Refused(f"{label}: צריך מספר")
    return float(value)


def clean_criteria(raw) -> dict:
    """The thresholds of an event as they are stored: {field: {"min", "max"}} for the
    fields that have at least one bound. Only the engine's own filter fields are accepted."""
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - {f for f, _label in selection.FILTER_FIELDS}:
        raise Refused("שדה סינון לא מוכר")
    out = {}
    for field, label in selection.FILTER_FIELDS:
        b = raw.get(field) or {}
        if not isinstance(b, dict):
            raise Refused(f"{label}: צריך מספר")
        lo, hi = _bound(b.get("min"), label), _bound(b.get("max"), label)
        if lo is not None and hi is not None and lo > hi:
            raise Refused(f"{label}: המספר ב\"מ-\" גדול מהמספר ב\"עד\"")
        if lo is not None or hi is not None:
            out[field] = {"min": lo, "max": hi}
    return out


def save(conn, now: datetime, data: dict, db_path: str = None) -> dict:
    """Set up a new event (no guid) or change one that is still ahead. The day must be
    today or later: the past is fixed, an event cannot be added to it."""
    service.roll_forward(conn, now, db_path)
    guid = (data.get("guid") or "").strip() or None
    day = planner.to_date(data.get("date"))
    if day is None:
        raise Refused("חסר תאריך לחלוקה")
    first = service.open_day(now)
    if day < first:
        raise Refused("התאריך כבר עבר. חלוקת חג קובעים להיום או ליום שעוד לא הגיע.")
    if day > first + timedelta(days=MAX_AHEAD_DAYS):
        raise Refused("התאריך רחוק מדי (יותר משנתיים קדימה)")
    code = str(data.get("holiday") or "").strip()
    if code not in {c["code"] for c in holiday_choices()}:
        raise Refused("צריך לבחור לאיזה חג החלוקה")
    portions = _whole(data.get("portions"), "מנות")
    reserve = _whole(data.get("reserve", 0), "רזרבה")
    criteria = clean_criteria(data.get("criteria"))
    balance = data.get("balance", False)
    if not isinstance(balance, bool):
        raise Refused("איזון הקהילות: צריך כן או לא")
    with store.tx(conn):
        if guid and _known(conn, guid)["closed_at"]:
            raise Refused(_PASSED)
        guid = store.save_event(conn, guid, day, code, portions, reserve, criteria, now, balance)
    return {"ok": True, "guid": guid}


def remove(conn, now: datetime, guid: str, db_path: str = None) -> dict:
    """Take away an event that has not happened yet. Nothing is erased — it can be brought
    back (restore) as long as its day has not passed. An event that passed is history and stays."""
    service.roll_forward(conn, now, db_path)
    if _known(conn, guid)["closed_at"]:
        raise Refused("החלוקה הזו כבר עברה ונמצאת בהיסטוריה, ואי אפשר למחוק אותה")
    try:
        with store.tx(conn):
            store.delete_event(conn, guid, now)
    except LookupError:
        raise Refused(_NOT_FOUND)
    return {"ok": True}


def restore(conn, now: datetime, guid: str, db_path: str = None) -> dict:
    """Bring back an event that was taken away, with everything that was set for it. Only
    while its day has not passed: the past is fixed, an event cannot be added to it."""
    service.roll_forward(conn, now, db_path)
    event = store.get_event(conn, guid)
    if event is None or not event["deleted_at"] or event["closed_at"]:
        raise Refused("אין חלוקה כזו לשחזר")
    if event["date"] < service.open_day(now):
        raise Refused("התאריך של החלוקה הזו כבר עבר, ואי אפשר לשחזר אותה")
    try:
        with store.tx(conn):
            store.restore_event(conn, guid)
    except LookupError:
        raise Refused("אין חלוקה כזו לשחזר")
    return {"ok": True, "guid": guid}


def _open_event(conn, now: datetime, guid: str, db_path: str = None) -> dict:
    service.roll_forward(conn, now, db_path)
    event = _known(conn, guid)
    if event["closed_at"]:
        raise Refused(_PASSED)
    return event


def set_manual(conn, now: datetime, guid: str, card: str, action: str, db_path: str = None) -> dict:
    """Put one person on the list / on the reserve / off the list of one event, or
    ('clear') back to automatic — the same four as for a week."""
    _open_event(conn, now, guid, db_path)
    if action != "clear" and action not in planner.MANUAL_ACTIONS:
        raise Refused("פעולה לא מוכרת")
    row = conn.execute("SELECT status FROM recipients WHERE guid=?", (card,)).fetchone()
    if row is None:
        raise Refused("הכרטיס לא נמצא")
    if action in (planner.MANUAL_ADD, planner.MANUAL_RESERVE) and (row["status"] or "") != planner.ACTIVE:
        raise Refused("הכרטיס מושהה, ואי אפשר להכניס אותו לרשימה")
    with store.tx(conn):
        store.set_event_manual(conn, guid, card, None if action == "clear" else action, now)
    return {"ok": True}


# ── paper and Excel ───────────────────────────────────────────────────────────
def _plan_of(conn, now: datetime, guid: str, db_path: str = None):
    _open_event(conn, now, guid, db_path)
    plans, ctx = _laid_out(conn, now, only=guid)
    plan = next((p for p in plans if p["guid"] == guid), None)
    if plan is None:
        raise Refused(_NOT_FOUND)
    return plan, ctx


def mark_printed(conn, now: datetime, guid: str, how: str, db_path: str = None) -> int:
    """Remember the event's list as it is being printed / exported — only so that a later
    change can be pointed out. It never holds the list in place."""
    if how not in ("print", "excel"):
        raise Refused("סוג הפקה לא מוכר")
    plan, _ctx = _plan_of(conn, now, guid, db_path)
    with store.tx(conn):
        store.set_event_print(conn, guid, how, [e["guid"] for e in plan["main"]],
                              [e["guid"] for e in plan["reserve_list"]], now)
    return 1


def paper(conn, now: datetime, guid: str, db_path: str = None) -> list:
    """The event's list ready for paper / Excel (one sheet), with the phones."""
    plan, ctx = _plan_of(conn, now, guid, db_path)
    cards = {r["guid"]: r for r in ctx["recipients"]}
    d = plan["date"]
    title = f"{holidays.dist_label(plan['holiday'])} · {service.day_name(d)} {d.strftime('%d/%m/%Y')}"
    return [service.paper_sheet(title, f"{d.strftime('%d-%m-%Y')} חג", plan, cards)]


def export_xlsx(conn, now: datetime, guid: str, db_path: str = None) -> bytes:
    return service.workbook(paper(conn, now, guid, db_path))


def file_date(conn, guid: str) -> str:
    event = store.get_event(conn, guid)
    return event["date"].isoformat() if event else date.today().isoformat()
