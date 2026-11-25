# -*- coding: utf-8 -*-
"""Between the store and the screen: which week is "now", closing weeks that passed,
and the answers the pages ask for. No web framework in here — plain functions that take a
database connection and the current time, so every one of them is testable.
"""
from datetime import date, datetime, timedelta

from . import config, planner, store
from .engine import selection

# A week closes on the Thursday after its Wednesday, at this hour — the same moment the
# desktop program's automatic registration opened (selection.AUTO_REGISTER_HOUR).
CLOSE_HOUR = selection.AUTO_REGISTER_HOUR


def current_week(now: datetime) -> date:
    """The Wednesday being prepared: this week's until Thursday 06:00, then the next."""
    return selection.upcoming_wednesday((now - timedelta(hours=CLOSE_HOUR)).date())


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
    }


def _plan(ctx: dict, start: date, weeks: int) -> list:
    return planner.plan_weeks(
        ctx["recipients"], ctx["received"], start=start, weeks=weeks, horizon=ctx["horizon"],
        weights=ctx["weights"], cooldown_weeks=ctx["cooldown"],
        portions=ctx["portions"], reserve=ctx["reserve"])


def roll_forward(conn, now: datetime, db_path: str = None) -> list:
    """Close every week that has passed and is not in the history yet, oldest first, each
    one as it is computed from the data of this moment (decision 25/11/2026). Returns the
    Wednesdays closed now ([] almost always). A fresh database starts from this week."""
    cur = current_week(now)
    done = store.closed_through(conn)
    if done is None:
        with store.tx(conn):
            if store.closed_through(conn) is None:
                store.set_meta(conn, "closed_through", (cur - timedelta(days=7)).isoformat())
        return []
    if done + timedelta(days=7) >= cur:
        return []
    if db_path:
        store.backup(db_path, config.backup_dir(), "before-closing-weeks", now)
    closed = []
    wed = done + timedelta(days=7)
    while wed < cur:
        with store.tx(conn):
            # re-read inside the write lock: another request may have closed it meanwhile
            latest = store.closed_through(conn)
            if latest is not None and latest >= wed:
                wed = latest + timedelta(days=7)
                continue
            week = _plan(_context(conn, now), wed, 1)[0]
            if store.close_week(conn, week, now, "auto"):
                closed.append(wed)
            elif latest is None or latest < wed:
                store.set_meta(conn, "closed_through", wed.isoformat())   # already written: move on
        wed += timedelta(days=7)
    return closed


def first_open_week(conn, now: datetime) -> date:
    cur = current_week(now)
    done = store.closed_through(conn)
    return max(cur, done + timedelta(days=7)) if done else cur


# ── answers for the pages ─────────────────────────────────────────────────────
def _week_summary(w: dict) -> dict:
    return {
        "date": w["date"].isoformat(), "portions": w["portions"], "reserve": w["reserve"],
        "regulars_due": w["regulars_due"], "main_regulars": w["main_regulars"],
        "main_one_timers": w["main_one_timers"], "empty_portions": w["empty_portions"],
        "cut": w["cut"], "counts": w["counts"], "warnings": w["warnings"],
        "main": [e["guid"] for e in w["main"]],
        "reserve_list": [e["guid"] for e in w["reserve_list"]],
    }


# What the screen needs about a person on a week's list — and nothing more. The planner's
# working numbers (need score, priority code, waiting days, last date) stay on the server;
# what matters of them is already said in words in `why`.
_ENTRY_FIELDS = ("guid", "name", "kind", "freq", "role", "why", "group")


def _public(entries: list) -> list:
    return [{k: e[k] for k in _ENTRY_FIELDS if k in e} for e in entries]


def _week_detail(w: dict) -> dict:
    d = _week_summary(w)
    d["main"], d["reserve_list"], d["out"] = _public(w["main"]), _public(w["reserve_list"]), _public(w["out"])
    d["one_time_queue"], d["one_time_slots"] = w["one_time_queue"], w["one_time_slots"]
    return d


def clamp_weeks(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 8
    return max(1, min(config.MAX_WEEKS, n))


def plan_overview(conn, now: datetime, weeks: int, db_path: str = None) -> dict:
    """The strip of coming weeks: for each one its numbers and who is on it (ids only)."""
    closed = roll_forward(conn, now, db_path)
    ctx = _context(conn, now)
    start = first_open_week(conn, now)
    plan = _plan(ctx, start, clamp_weeks(weeks))
    return {
        "today": now.date().isoformat(), "current_week": start.isoformat(),
        "closed_now": [d.isoformat() for d in closed],
        "defaults": {"portions": ctx["portions"], "reserve": ctx["reserve"],
                     "cooldown_weeks": ctx["cooldown"]},
        "weeks": [_week_summary(w) for w in plan],
    }


def week_detail(conn, now: datetime, wed: date, db_path: str = None) -> dict:
    """One coming week in full: main / reserve / not this week, each with its reason."""
    roll_forward(conn, now, db_path)
    start = first_open_week(conn, now)
    if wed.weekday() != 2:
        raise ValueError("not a Wednesday")
    index = (wed - start).days // 7
    if index < 0:
        raise LookupError("this week has passed")
    if index >= config.MAX_WEEKS:
        raise LookupError("too far ahead")
    plan = _plan(_context(conn, now), start, index + 1)
    return _week_detail(plan[index])


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
            others.append(item)
    return {"participants": part, "others": others}
