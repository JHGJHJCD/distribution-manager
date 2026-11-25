# -*- coding: utf-8 -*-
"""The desktop program's own way of building a week — kept ONLY as a yardstick for tests.

`build_week` + `simulate` are the composition that produced the lists sent to the manager
since 10/2026 (regular 'schedule' mode: database.get_weekly_list -> selection.limit_due_regulars
-> database.get_one_time_list -> selection.assign_roles, and after each week the MAIN list is
recorded with database.bulk_add_distributions). The website must give the same lists.

SAFETY: `load()` points APPDATA at a throw-away folder BEFORE the desktop data layer is
imported, and refuses to go on unless the database path really is inside it — so nothing
here can reach the real program's data, whatever else goes wrong.
"""
import datetime as dt
import os
import sqlite3
import sys

_state = {"db": None, "root": None}


class SimDate(dt.date):
    """A date whose today() is the simulated day (the desktop code asks the clock)."""
    _today = None

    @classmethod
    def today(cls):
        t = cls._today
        return dt.date(t.year, t.month, t.day) if t else dt.date.today()


def load(tmp_root: str):
    """Import the desktop data layer against a private folder. Returns the module."""
    if _state["db"] is not None:
        return _state["db"]
    if "database" in sys.modules:
        raise RuntimeError("database.py was already imported — the oracle must load it itself")
    tmp_root = os.path.abspath(tmp_root)
    os.makedirs(tmp_root, exist_ok=True)
    os.environ["APPDATA"] = tmp_root
    os.environ.pop("MANHAL_ALLOW_REAL_SYNC", None)
    import database as db
    if not os.path.abspath(db.DB_PATH).startswith(tmp_root + os.sep):
        raise RuntimeError(f"refusing to run: the desktop database path {db.DB_PATH!r} is outside {tmp_root!r}")
    _state["db"], _state["root"] = db, tmp_root
    return db


def use_db(path: str):
    """Point the desktop data layer at `path` (must be inside the private folder)."""
    db = _state["db"]
    path = os.path.abspath(path)
    if not path.startswith(_state["root"] + os.sep):
        raise RuntimeError("the oracle only works inside its private folder")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db.DB_PATH = path
    db.BACKUP_DIR = os.path.join(os.path.dirname(path), "backups")
    return db


class clock:
    """with clock(): ... — the desktop code reads SimDate.today() inside the block."""

    def __enter__(self):
        import selection
        db = _state["db"]
        self._old = (db.date, selection._date)
        db.date = selection._date = SimDate
        return SimDate

    def __exit__(self, *exc):
        import selection
        _state["db"].date, selection._date = self._old
        SimDate._today = None
        return False


def copy_db(src: str, dest: str):
    """SQLite's own backup (a plain file copy would miss what still sits in the -wal file)."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    a, b = sqlite3.connect(src), sqlite3.connect(dest)
    try:
        a.backup(b)
    finally:
        b.close()
        a.close()


def build_week(wed: dt.date, products: int, reserve: int) -> dict:
    """One Wednesday, exactly as the desktop screen composes it in the regular mode."""
    import selection
    db = _state["db"]
    weights = db.get_need_weights()
    base = db.get_weekly_list(area_filter="הכל", on_date=wed)
    regs_due = len(base)
    kept = selection.limit_due_regulars(base, weights, products, reserve, 0)
    cut = len(kept) < regs_due or any(r.get("_reserve") for r in kept)
    main, res = [], []
    for r in kept:
        (res if r.get("_reserve") else main).append(r["guid"])
    slots = selection.one_time_slots(products, regs_due, 0)
    one = [r for r in db.get_one_time_list(area_filter="הכל", on_date=wed) if r.get("in_distribution")]
    selection.assign_roles(one, slots, reserve if not cut else 0)
    for r in one:
        if r.get("_role") == selection.ROLE_MAIN:
            main.append(r["guid"])
        elif r.get("_role") == selection.ROLE_RESERVE:
            res.append(r["guid"])
    return {"date": wed, "regulars_due": regs_due, "cut": cut, "main": main, "reserve_list": res,
            "queue": [r["guid"] for r in one]}


def record(guids: list, day: dt.date, holiday: str = "", not_received: list = None, name: str = "sim"):
    """Record a round on `day` (the clock must already stand on or after it)."""
    db = _state["db"]
    rows = [dict(r) for r in (db.get_recipient_by_guid(g) for g in guids) if r]
    missed = [dict(r) for r in (db.get_recipient_by_guid(g) for g in (not_received or [])) if r]
    if rows or missed:
        db.bulk_add_distributions(rows, day.isoformat(), "מצרכים", 1, "בדיקה", dist_name=name,
                                  not_received=missed, holiday=holiday)


def simulate(start: dt.date, weeks: int, products: int, reserve: int, prior: list = None) -> list:
    """`weeks` Wednesdays in a row on the CURRENT database (give it a throw-away copy):
    after each week its MAIN list is recorded as received, the reserve is not."""
    out = []
    with clock() as sim:
        for p in (prior or []):
            import selection
            day = selection.round_wednesday(dt.date.fromisoformat(str(p["date"])[:10]))
            sim._today = day
            record(list(p["guids"]), day, name="sent")
        wed = start
        for _ in range(weeks):
            sim._today = wed
            w = build_week(wed, products, reserve)
            out.append(w)
            record(w["main"], wed)
            wed += dt.timedelta(days=7)
    return out
