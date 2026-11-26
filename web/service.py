# -*- coding: utf-8 -*-
"""Between the store and the screen: which week is "now", closing weeks that passed,
and the answers the pages ask for. No web framework in here — plain functions that take a
database connection and the current time, so every one of them is testable.
"""
import io
from datetime import date, datetime, timedelta

from . import config, planner, store
from .engine import holidays, selection

# A week closes on the Thursday after its Wednesday, at this hour — the same moment the
# desktop program's automatic registration opened (selection.AUTO_REGISTER_HOUR).
CLOSE_HOUR = selection.AUTO_REGISTER_HOUR
MAX_PORTIONS = 2000            # sanity ceiling for a number typed by hand


class Refused(Exception):
    """A request that cannot be carried out; the message is shown to the user (Hebrew)."""


def current_week(now: datetime) -> date:
    """The Wednesday being prepared: this week's until Thursday 06:00, then the next."""
    return selection.upcoming_wednesday(open_day(now))


def open_day(now: datetime) -> date:
    """The first day whose round is not over yet. Every round — a Wednesday's list or a
    holiday event — becomes history at 06:00 on the morning after its day; a round dated
    before this day has passed."""
    return (now - timedelta(hours=CLOSE_HOUR)).date()


def event_name(code: str, day: date) -> str:
    """'חלוקת פסח 18/04/2027' / 'חלוקת חג 18/04/2027' — the name an event carries in the history."""
    return f"{holidays.dist_label(code or selection.HOLIDAY_ANY)} {day.strftime('%d/%m/%Y')}"


def _context(conn, now: datetime) -> dict:
    settings = store.get_settings(conn)
    return {
        "recipients": store.load_recipients(conn),
        "received": store.load_received(conn),
        "weights": planner.need_weights(settings),
        "cooldown": store.int_setting(settings, "onetime_cooldown_weeks",
                                      selection.ONE_TIME_COOLDOWN_WEEKS_DEFAULT),
        "portions": store.int_setting(settings, "default_portions", config.DEFAULT_PORTIONS),
        "reserve": store.int_setting(settings, "default_reserve", config.DEFAULT_RESERVE),
        "horizon": selection.upcoming_wednesday(now.date()),
        "manual": store.load_manual(conn),
        "numbers": store.load_numbers(conn),
        "modes": store.load_modes(conn),                # the weeks that are cut by need score
        "pinned": store.community_pcts(settings),       # the percentage fixed for a community
        "prints": store.load_prints(conn),
        "events": store.load_events(conn),              # holiday events that are still ahead
        "event_prints": store.load_event_prints(conn),
    }


def _timeline(ctx: dict, start: date, weeks: int) -> dict:
    """The coming weeks AND the holiday events among them, in date order (planner.plan_timeline)."""
    return planner.plan_timeline(
        ctx["recipients"], ctx["received"], start=start, weeks=weeks, horizon=ctx["horizon"],
        weights=ctx["weights"], cooldown_weeks=ctx["cooldown"],
        portions=ctx["portions"], reserve=ctx["reserve"],
        per_week=ctx["numbers"], manual=ctx["manual"], events=ctx["events"],
        modes=ctx["modes"], pinned=ctx["pinned"])


def _plan(ctx: dict, start: date, weeks: int) -> list:
    return _timeline(ctx, start, weeks)["weeks"]


def roll_forward(conn, now: datetime, db_path: str = None) -> list:
    """Close every week that has passed and is not in the history yet, oldest first, each
    one as it is computed from the data of this moment (decision 25/11/2026) — what the
    manager set by hand for it included. Holiday events whose day has passed close with
    them, in date order. Returns the Wednesdays closed now ([] almost always). A fresh
    database starts from this week."""
    return _roll(conn, now, db_path)[0]


def _week_goes_first(wed: date, event_day: date) -> bool:
    """Of a week and a holiday event that are both over, which is written first: the one
    dated earlier, and on the same day the week (the event is the extra round of that day).
    The same order planner.plan_timeline lays them out in."""
    return wed <= event_day


def _roll(conn, now: datetime, db_path: str = None) -> tuple:
    """(Wednesdays closed now, holiday events closed now as {guid, date, name}).

    A round is over at 06:00 on the morning after its day. The rounds that are over are
    closed ONE BY ONE in date order — a week before an event of the same day, exactly the
    order they are planned in — and each is computed after the ones before it are already
    history, so what is written is what the screen showed."""
    cur, day = current_week(now), open_day(now)
    done = store.closed_through(conn)
    if done is None:
        with store.tx(conn):
            if store.closed_through(conn) is None:
                store.set_meta(conn, "closed_through", (cur - timedelta(days=7)).isoformat())
        return [], []
    if done + timedelta(days=7) >= cur and store.first_passed_event(conn, day) is None:
        return [], []
    if db_path:
        store.backup(db_path, config.backup_dir(), "before-closing-weeks", now)
    weeks, events = [], []
    while True:
        with store.tx(conn):
            # everything is re-read inside the write lock: another request may have closed it meanwhile
            wed = store.closed_through(conn) + timedelta(days=7)
            event = store.first_passed_event(conn, day)
            week_over = wed < cur
            if not week_over and event is None:
                break
            if week_over and (event is None or _week_goes_first(wed, event["date"])):
                week = _timeline(_context(conn, now), wed, 1)["weeks"][0]
                if store.close_week(conn, week, now, "auto"):
                    weeks.append(wed)
                else:
                    store.set_meta(conn, "closed_through", wed.isoformat())   # already written: move on
            else:
                # every week up to the event's day is history by now, so the event is the
                # first round ahead: nothing has to be laid out before it
                laid = _timeline(_context(conn, now), wed, 0)["events"]
                plan = next((p for p in laid if p["guid"] == event["guid"]), None)
                if plan is None:                       # cannot happen; never loop on it
                    raise RuntimeError("a passed holiday event was not laid out")
                name = event_name(plan["holiday"], plan["date"])
                if not store.close_event(conn, plan, name, now):   # cannot happen; never loop on it
                    raise RuntimeError("a passed holiday event could not be closed")
                events.append({"guid": plan["guid"], "date": plan["date"], "name": name})
    return weeks, events


def first_open_week(conn, now: datetime) -> date:
    cur = current_week(now)
    done = store.closed_through(conn)
    return max(cur, done + timedelta(days=7)) if done else cur


def _open_index(conn, now: datetime, wed: date) -> int:
    """How many weeks after the first open one `wed` is; refuses a week that is not a
    coming Wednesday."""
    if wed.weekday() != 2:
        raise ValueError("not a Wednesday")
    index = (wed - first_open_week(conn, now)).days // 7
    if index < 0:
        raise LookupError("this week has passed")
    if index >= config.MAX_WEEKS:
        raise LookupError("too far ahead")
    return index


# ── answers for the pages ─────────────────────────────────────────────────────
def _print_note(w: dict, ctx: dict, names: dict = None):
    """None when the week was never printed; else when / how, and what changed since."""
    return since_print(ctx["prints"].get(w["date"]), [e["guid"] for e in w["main"]], names)


def since_print(snap, now_main: list, names: dict = None):
    """What changed on a list (a week's or a holiday event's) since it was last printed /
    exported: None when it never was. Only the MAIN list is compared."""
    if not snap:
        return None
    added = [g for g in now_main if g not in set(snap["main"])]
    removed = [g for g in snap["main"] if g not in set(now_main)]
    note = {"printed_at": snap["printed_at"], "how": snap["how"], "changed": bool(added or removed),
            "added": len(added), "removed": len(removed)}
    if names is not None:
        note["added_names"] = [names.get(g, "כרטיס שנמחק") for g in added]
        note["removed_names"] = [names.get(g, "כרטיס שנמחק") for g in removed]
    return note


def _week_summary(w: dict, ctx: dict) -> dict:
    return {
        "date": w["date"].isoformat(), "portions": w["portions"], "reserve": w["reserve"],
        "regulars_due": w["regulars_due"], "main_regulars": w["main_regulars"],
        "main_one_timers": w["main_one_timers"], "empty_portions": w["empty_portions"],
        "cut": w["cut"], "counts": w["counts"], "warnings": w["warnings"], "by_score": w["by_score"],
        "main": [e["guid"] for e in w["main"]],
        "reserve_list": [e["guid"] for e in w["reserve_list"]],
        "numbers_set": w["date"] in ctx["numbers"],
        "manual_count": len(ctx["manual"].get(w["date"], {})),
        "print": _print_note(w, ctx),
    }


# What the screen needs about a person on a week's list — and nothing more. The planner's
# working numbers (need score, priority code, waiting days, last date) stay on the server;
# what matters of them is already said in words in `why`.
_ENTRY_FIELDS = ("guid", "name", "kind", "freq", "role", "why", "group", "manual", "community", "fill")


def _public(entries: list) -> list:
    return [{k: e[k] for k in _ENTRY_FIELDS if k in e} for e in entries]


def _week_detail(w: dict, ctx: dict) -> dict:
    d = _week_summary(w, ctx)
    d["main"], d["reserve_list"], d["out"] = _public(w["main"]), _public(w["reserve_list"]), _public(w["out"])
    d["one_time_queue"], d["one_time_slots"] = w["one_time_queue"], w["one_time_slots"]
    d["print"] = _print_note(w, ctx, {r["guid"]: r.get("full_name") or "" for r in ctx["recipients"]})
    return d


def clamp_weeks(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 8
    return max(1, min(config.MAX_WEEKS, n))


def plan_overview(conn, now: datetime, weeks: int, db_path: str = None) -> dict:
    """The strip of coming weeks: for each one its numbers and who is on it (ids only)."""
    closed, closed_events = _roll(conn, now, db_path)
    ctx = _context(conn, now)
    start = first_open_week(conn, now)
    line = _timeline(ctx, start, clamp_weeks(weeks))
    return {
        "today": now.date().isoformat(), "current_week": start.isoformat(),
        "closed_now": [d.isoformat() for d in closed],
        "closed_events_now": [e["name"] for e in closed_events],
        "defaults": {"portions": ctx["portions"], "reserve": ctx["reserve"],
                     "cooldown_weeks": ctx["cooldown"]},
        "weeks": [_week_summary(w, ctx) for w in line["weeks"]],
        # the holiday events that fall among these weeks: where they sit, and how many receive
        "events": [{"guid": e["guid"], "date": e["date"].isoformat(),
                    "name": holidays.dist_label(e["holiday"]), "main": [x["guid"] for x in e["main"]],
                    "reserve_list": [x["guid"] for x in e["reserve_list"]], "portions": e["portions"]}
                   for e in line["events"]],
    }


def week_detail(conn, now: datetime, wed: date, db_path: str = None) -> dict:
    """One coming week in full: main / reserve / not this week, each with its reason."""
    roll_forward(conn, now, db_path)
    index = _open_index(conn, now, wed)
    ctx = _context(conn, now)
    plan = _plan(ctx, first_open_week(conn, now), index + 1)
    return _week_detail(plan[index], ctx)


def people(conn) -> dict:
    """Every card, for the search box: who takes part in the lists and who does not (with
    the reason). Names only — no phones or other details leave the store here."""
    part, others = [], []
    for r in store.load_recipients(conn):
        kind = planner.participation(r) if planner.is_active(r) else ""
        item = {"guid": r["guid"], "name": r.get("full_name") or ""}
        if kind:
            item.update(kind=kind, freq=(r.get("frequency") or "").strip())
            part.append(item)
        else:
            item["why"] = planner.why_not_participating(r)
            item["active"] = planner.is_active(r)
            others.append(item)
    return {"participants": part, "others": others}


# ── stage 2: what the manager sets by hand ────────────────────────────────────
def set_manual(conn, now: datetime, wed: date, guid: str, action: str, db_path: str = None) -> None:
    """Put one person on the list / on the reserve / off the list of one coming week, or
    ('clear') back to automatic. Only a coming week can be changed, only an active card."""
    roll_forward(conn, now, db_path)
    try:
        _open_index(conn, now, wed)
    except (ValueError, LookupError):
        raise Refused("אפשר לשנות רק שבוע שעוד לא עבר")
    if action != "clear" and action not in planner.MANUAL_ACTIONS:
        raise Refused("פעולה לא מוכרת")
    row = conn.execute("SELECT status FROM recipients WHERE guid=?", (guid,)).fetchone()
    if row is None:
        raise Refused("הכרטיס לא נמצא")
    if action in (planner.MANUAL_ADD, planner.MANUAL_RESERVE) and (row["status"] or "") != planner.ACTIVE:
        raise Refused("הכרטיס מושהה, ואי אפשר להכניס אותו לרשימה")
    with store.tx(conn):
        store.set_manual(conn, wed, guid, None if action == "clear" else action, now)


def set_numbers(conn, now: datetime, wed: date, portions, reserve, db_path: str = None) -> None:
    """The number of portions and the size of the reserve for one coming week; None for
    both = back to the ordinary numbers."""
    roll_forward(conn, now, db_path)
    try:
        _open_index(conn, now, wed)
    except (ValueError, LookupError):
        raise Refused("אפשר לשנות רק שבוע שעוד לא עבר")
    for v in (portions, reserve):
        if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= MAX_PORTIONS):
            raise Refused(f"צריך מספר שלם בין 0 ל-{MAX_PORTIONS}")
    with store.tx(conn):
        store.set_numbers(conn, wed, portions, reserve, now)


def set_mode(conn, now: datetime, wed: date, mode: str, db_path: str = None) -> None:
    """How one coming week picks among the regulars in turn when its portions are short:
    'scored' = by need score, 'wait' = the ordinary way (whoever waited longest)."""
    roll_forward(conn, now, db_path)
    try:
        _open_index(conn, now, wed)
    except (ValueError, LookupError):
        raise Refused("אפשר לשנות רק שבוע שעוד לא עבר")
    if mode not in planner.WEEK_MODES:
        raise Refused("דרך חלוקה לא מוכרת")
    with store.tx(conn):
        store.set_mode(conn, wed, None if mode == planner.MODE_WAIT else mode, now)


def _range(conn, now: datetime, start: date, weeks: int, db_path: str = None):
    """The planned weeks start .. start+weeks-1 (coming weeks only) and the context."""
    roll_forward(conn, now, db_path)
    try:
        index = _open_index(conn, now, start)
    except (ValueError, LookupError):
        raise Refused("הטווח צריך להתחיל ביום רביעי שעוד לא עבר")
    weeks = max(1, min(int(weeks), config.MAX_WEEKS - index))
    ctx = _context(conn, now)
    plan = _plan(ctx, first_open_week(conn, now), index + weeks)
    return plan[index:], ctx


def mark_printed(conn, now: datetime, start: date, weeks: int, how: str, db_path: str = None) -> int:
    """Remember the lists of these weeks as they are being printed / exported, so that a
    later change can be pointed out. It never holds a list in place."""
    if how not in ("print", "excel"):
        raise Refused("סוג הפקה לא מוכר")
    plan, _ = _range(conn, now, start, weeks, db_path)
    with store.tx(conn):
        for w in plan:
            store.set_print(conn, w["date"], how, [e["guid"] for e in w["main"]],
                            [e["guid"] for e in w["reserve_list"]], now)
    return len(plan)


_KIND_LABEL = {planner.KIND_REGULAR: "קבוע", planner.KIND_ONE_TIME: "חד-פעמי",
               planner.KIND_OTHER: "כרטיס בלבד"}
_DAY_NAME = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]      # date.weekday()


def day_name(d: date) -> str:
    return "יום " + _DAY_NAME[d.weekday()] if d.weekday() != 5 else "שבת"


def _paper_rows(entries: list, cards: dict) -> list:
    """The rows of a list for paper / Excel. (Phones leave the store only through here.)"""
    out = []
    for i, e in enumerate(entries, 1):
        c = cards.get(e["guid"], {})
        phones = [str(c.get(k) or "").strip() for k in ("phone1", "phone2", "phone3")]
        last = planner.to_date(e.get("last"))
        out.append({
            "n": i, "name": e["name"], "phones": " · ".join(p for p in phones if p),
            "souls": c.get("souls") or "", "kind": _KIND_LABEL.get(e["kind"], ""),
            "freq": e["freq"] if e["kind"] == planner.KIND_REGULAR else "",
            "last": last.strftime("%d/%m/%Y") if last else "",
            "manual": bool(e.get("manual")),
        })
    return out


def paper_sheet(title: str, sheet: str, plan: dict, cards: dict) -> dict:
    """One list (a week's or a holiday event's) ready for paper / Excel. On paper the list
    is by name (easy to find a family at the table); the reserve keeps its own order,
    because there the order is who comes in first."""
    return {"date": plan["date"].isoformat(), "title": title, "sheet": sheet, "portions": plan["portions"],
            "main": _paper_rows(sorted(plan["main"], key=lambda e: e["name"]), cards),
            "reserve_list": _paper_rows(plan["reserve_list"], cards),
            "warnings": plan["warnings"]}


def print_weeks(conn, now: datetime, start: date, weeks: int, db_path: str = None) -> list:
    """The lists of a range of coming weeks, ready for paper / Excel: for each person the
    name, the phones, the number of souls and the kind."""
    plan, ctx = _range(conn, now, start, weeks, db_path)
    cards = {r["guid"]: r for r in ctx["recipients"]}
    return [paper_sheet(f"חלוקת רביעי {w['date'].strftime('%d/%m/%Y')}", w["date"].strftime("%d-%m-%Y"), w, cards)
            for w in plan]


def _keep_as_text(cell, value) -> None:
    """A name or a phone is text, never a formula — also when it starts with '=' or '+'."""
    if isinstance(value, str) and value[:1] in "=+-@":
        cell.data_type = "s"


def export_xlsx(conn, now: datetime, start: date, weeks: int, db_path: str = None) -> bytes:
    """One workbook, a right-to-left sheet per week: the list, then the reserve."""
    return workbook(print_weeks(conn, now, start, weeks, db_path))


def workbook(data: list) -> bytes:
    """An Excel file from paper sheets (paper_sheet): a right-to-left sheet for each."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.properties import PageSetupProperties

    def put(ws, row, col, value, **style):
        cell = ws.cell(row=row, column=col, value=value)
        _keep_as_text(cell, value)
        for k, v in style.items():
            setattr(cell, k, v)
        return cell

    wb = Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="E3F3ED")
    headers = ["#", "שם", "טלפון", "נפשות", "סוג", "תדירות", "חלוקה אחרונה"]
    widths = [5, 26, 30, 8, 11, 12, 15]
    for w in data:
        ws = wb.create_sheet(w["sheet"])
        ws.sheet_view.rightToLeft = True
        for i, width in enumerate(widths):
            ws.column_dimensions["ABCDEFG"[i]].width = width
        put(ws, 1, 1, w["title"], font=Font(bold=True, size=14))
        put(ws, 2, 1, f"{len(w['main'])} מקבלים · {len(w['reserve_list'])} ברזרבה · {w['portions']} מנות")
        r = 4
        for title, rows in (("מקבלים", w["main"]), ("רזרבה (נכנסים רק אם מישהו לא מגיע)", w["reserve_list"])):
            put(ws, r, 1, title, font=Font(bold=True, size=12))
            r += 1
            for c, h in enumerate(headers, 1):
                put(ws, r, c, h, font=Font(bold=True), fill=head_fill, border=box,
                    alignment=Alignment(horizontal="center"))
            r += 1
            for row in rows:
                values = [row["n"], row["name"], row["phones"], row["souls"], row["kind"], row["freq"], row["last"]]
                for c, v in enumerate(values, 1):
                    put(ws, r, c, v, border=box)
                r += 1
            r += 1
        ws.page_setup.orientation = "portrait"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
