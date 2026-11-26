# -*- coding: utf-8 -*-
"""Stage 5 — the comparison with the desktop program, on a COPY of real data.

Run by hand on the fund's own computer: double-click web\\compare_with_old.bat, or

    <python 3.12> web/tests/local_check_real.py --from <data.db>
                  [--sent-history <json>] [--weeks 13] [--portions 52] [--reserve 10]
                  [--start YYYY-MM-DD] [--report [file.html]] [--open] [--quick]

What it does. The source file is only READ, as plain bytes, into a temp folder — nothing is
written to it or beside it; everything else happens on copies inside that folder, which is
removed at the end. The
copy is imported into the site (web/import_old.py) and, apart from that, handed to the
desktop program's own code (web/tests/oracle_old.py). Both then lay out the same rounds:

  * ordinary weeks (who waited longest), as many as asked for;
  * the same weeks with fewer portions than regulars in turn (so the cut decides);
  * the same weeks "by score";
  * a holiday list for every holiday that somebody is marked for — plain, split between the
    communities, and with the filter that is saved in the desktop program;
  * the ordinary weeks against the desktop program EXACTLY AS IT IS TODAY, where a holiday /
    bonus portion pauses a one-timer. A difference there is the decision "חג לא נספר"
    (26/11/2026) at work, and is reported as expected — not as a fault.

Every list must match: the same people, in the same order, the same reserve.

PRIVACY: the report and everything printed carry NUMBERS and fixed words only — no name,
no phone, no id, no free text out of the data (a reason is a fixed category; a community
is never named). It is safe to pass on.

Not part of run_all.py (it needs real data, which never enters the repository). The tool
itself is tested on invented people: web/tests/test_compare.py.
"""
import argparse
import html
import json
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
import webbrowser
from datetime import date, datetime, timedelta

from _util import guids

import oracle_old as old

from web import config, event_service, import_old, planner, service, store
from web.engine import selection
from web.service import Refused

SHOWN = 12                    # how many kinds of difference a differing list spells out (never a name)
HOLIDAY_WEEKS = 4             # how many weeks a holiday scenario lays out around its event
HOLIDAY_RESERVE = 5
FAR = 10 ** 5                 # "portions for everybody": to count who is eligible for a holiday list

# why the site left somebody off a list — fixed words for each of its own categories
WHY_OUT = {
    planner.OUT_REG_WAIT: "קבוע שתורו עוד לא הגיע, או שכבר קיבל השבוע",
    planner.OUT_REG_CUT: "קבוע שתורו הגיע, אבל המנות נגמרו",
    planner.OUT_ONE_PAUSE: "חד-פעמי בהפסקה אחרי שקיבל",
    planner.OUT_ONE_QUEUE: "חד-פעמי שמחכה בתור: המנות והרזרבה מלאות",
    planner.OUT_NO_PORTIONS: "אין מנות",
    planner.OUT_REMOVED: "הוסר ביד",
    planner.OUT_EV_MISSING: "חסר לו נתון שמסננים לפיו",
    planner.OUT_EV_CUT: "עובר את הסינון, אבל המנות והרזרבה נגמרו",
    planner.OUT_EV_FILTER: "לא עובר את הסינון",
    planner.OUT_EV_OTHER: "מסומן לחגים אחרים בלבד",
}
PLACE = {"main": "ברשימה", "reserve": "ברזרבה", "out": "לא ברשימה", "absent": "לא משתתף"}


# ── the two programs, each on its own copy ────────────────────────────────────
SNAPSHOT_TRIES = 20


def _read_pair(src: str) -> tuple:
    """The bytes of the data file and of its -wal file (where the desktop program keeps what
    it has not folded into the data file yet; b"" when there is none)."""
    with open(src, "rb") as f:
        data = f.read()
    try:
        with open(src + "-wal", "rb") as f:
            wal = f.read()
    except FileNotFoundError:
        wal = b""
    return data, wal


def snapshot(src: str, dest: str) -> None:
    """A copy of the data file to work on, taken WITHOUT WRITING ANYTHING NEAR THE SOURCE.

    Even a read-only SQLite connection leaves two working files (-shm, -wal) beside a file of
    the desktop program (it is in WAL mode). So the source is not opened with SQLite at all:
    its bytes, and those of its -wal file, are read twice, and the copy is taken only when
    nothing changed in between (the desktop program may be running). SQLite then opens the
    COPY, folds the -wal in, and the copy is checked to be sound."""
    if not os.path.isfile(src):
        raise FileNotFoundError(f"the data file was not found: {src}")
    for _ in range(SNAPSHOT_TRIES):
        pair = _read_pair(src)
        time.sleep(0.05)
        if pair == _read_pair(src):
            break
    else:
        raise RuntimeError("the data file kept changing while it was being copied - "
                           "close the desktop program and run the comparison again")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(pair[0])
    if pair[1]:
        with open(dest + "-wal", "wb") as f:
            f.write(pair[1])
    c = sqlite3.connect(dest)
    try:
        sound = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.DatabaseError:
        sound = False
    finally:
        c.close()
    if not sound:
        raise RuntimeError("the copy of the data file is not a sound database")


def assert_no_sync() -> None:
    """The desktop program shares its data with a second computer through a folder. Its code
    must never write there on behalf of a COPY: what is recorded on a copy are simulated
    weeks, not real ones. The switch lives in a file beside the data file (sync_state.json),
    and that file is never copied — so for a copy the sharing is off. This makes sure of it
    before the desktop code writes a single row."""
    from utils import sync                       # the desktop program's own module (after oracle_old.load)
    if sync.is_enabled():
        raise RuntimeError("the desktop program's sharing between computers is switched on for the copy - "
                           "nothing was written, and the comparison stops here")


class Both:
    """The site and the desktop program, each working on copies of one snapshot."""

    def __init__(self, snap: str, work: str, now: datetime, sent_path: str = None):
        self.snap, self.now = snap, now
        self.tag = uuid.uuid4().hex[:8]
        self.db = old.load(os.path.join(work, "desktop"))
        self.root = old._state["root"]             # where the desktop code is allowed to work (set once per process)
        self.sent = []
        if sent_path:
            with open(sent_path, encoding="utf-8") as f:
                self.sent = json.load(f)
        self.web_db = os.path.join(work, f"web-{self.tag}", "haluka.db")
        self.import_report = import_old.import_old(snap, self.web_db, sent_history=sent_path, now=now)
        conn = store.connect(self.web_db)
        try:
            settings = store.get_settings(conn)
            self.cards = {r["guid"]: r for r in store.load_recipients(conn)}
        finally:
            conn.close()
        self.weights = planner.need_weights(settings)
        self.cooldown = store.int_setting(settings, "onetime_cooldown_weeks", 4)
        self.pinned = store.community_pcts(settings)
        self.horizon = selection.upcoming_wednesday(now.date())
        self.runs = 0
        # what the desktop program has saved for itself, read from a copy of its own
        self._fresh_desktop()
        self.old_pcts = self.db.get_community_quotas()
        self.saved_filter = self.db.get_filter_criteria()

    def _fresh_desktop(self) -> None:
        """A new copy of the snapshot for the desktop code, started as the program starts."""
        self.runs += 1
        path = os.path.join(self.root, f"{self.tag}-{self.runs}", "ManhalHaluka", "data.db")
        old.copy_db(self.snap, path)
        old.use_db(path)
        assert_no_sync()
        with old.clock() as clk:
            clk._today = self.now.date()
            self.db.init_db()

    def site(self, start, weeks, portions, reserve, events=None, scored=()) -> dict:
        conn = store.connect(self.web_db)
        try:
            recipients, received = store.load_recipients(conn), store.load_received(conn)
        finally:
            conn.close()
        return planner.plan_timeline(
            recipients, received, start=start, weeks=weeks, horizon=self.horizon, weights=self.weights,
            cooldown_weeks=self.cooldown, portions=portions, reserve=reserve,
            events=[dict(e) for e in events or []], modes={w: planner.MODE_SCORED for w in scored},
            pinned=self.pinned)

    def desktop(self, start, weeks, portions, reserve, events=None, scored=(), as_it_is=False) -> dict:
        self._fresh_desktop()
        return old.simulate_line(start, weeks, portions, reserve, prior=self.sent,
                                 events=[dict(e) for e in events or []], scored_weeks=set(scored),
                                 community_pcts=self.old_pcts, extra_counts=as_it_is)


# ── comparing one list ────────────────────────────────────────────────────────
def kind_of(entry, card) -> str:
    """What KIND of recipient this is — never who."""
    if entry:
        if entry["kind"] == planner.KIND_REGULAR:
            return "קבוע " + (entry.get("freq") or "")
        return "חד-פעמי" if entry["kind"] == planner.KIND_ONE_TIME else "כרטיס שאינו בחלוקה הרגילה"
    if card is None:
        return "כרטיס שלא עבר לאתר"
    return "כרטיס פעיל שלא משתתף" if planner.is_active(card) else "כרטיס מושהה"


def differences(a: dict, old_main: list, old_reserve: list, cards: dict) -> list:
    """One anonymous line for each person the two programs placed differently: his kind, where
    each program put him, and the site's category for leaving him out."""
    site = {}
    for key, place in (("main", "main"), ("reserve_list", "reserve"), ("out", "out")):
        for e in a[key]:
            site.setdefault(e["guid"], (place, e))
    theirs = {g: "main" for g in old_main}
    for g in old_reserve:
        theirs.setdefault(g, "reserve")
    rows = []
    for g in dict.fromkeys(list(theirs) + [g for g, (place, _e) in site.items() if place != "out"]):
        place, entry = site.get(g, ("absent", None))
        other = theirs.get(g, "out")
        if place == other or (place in ("out", "absent") and other == "out"):
            continue
        why = ""
        if place == "out":
            why = WHY_OUT.get(entry.get("group"), "")
        elif entry is not None and entry.get("fill"):
            why = "נכנס כדי להשלים את החלק של הקהילה שלו"
        rows.append({"who": kind_of(entry, cards.get(g)).strip(), "site": place, "old": other, "why": why})
    return rows


def _verdict(row: dict, a: dict, old_main: list, old_reserve: list, cards: dict) -> dict:
    mine = guids(a["main"])
    row.update(main=len(mine), main_old=len(old_main), reserve=len(a["reserve_list"]), reserve_old=len(old_reserve),
               same_people=set(mine) == set(old_main), same_order=mine == old_main)
    row["same"] = row["same_order"] and row["same_reserve"] and row.get("same_in_turn", True)
    row["differences"] = [] if row["same"] else differences(a, old_main, old_reserve, cards)
    row["first_out_of_order"] = 0
    if row["same_people"] and not row["same_order"]:
        row["first_out_of_order"] = next(i + 1 for i, (x, y) in enumerate(zip(mine, old_main)) if x != y)
    return row


def compare_week(a: dict, b: dict, reserve: int, cards: dict) -> dict:
    """One Wednesday: the site's week `a` beside the desktop program's week `b`."""
    if not b["cut"]:
        old_reserve = list(b["reserve_list"])
        same_reserve = guids(a["reserve_list"]) == old_reserve
    else:
        # rule 3 (21/10/2026): the reserve is always shown — after the regulars who were cut,
        # the desktop SCREEN tops it up from the one-timers' queue (web/tests/test_vs_old.py)
        regs = [e["guid"] for e in a["reserve_list"] if e["kind"] == planner.KIND_REGULAR]
        ones = [e["guid"] for e in a["reserve_list"] if e["kind"] == planner.KIND_ONE_TIME]
        top_up = b["queue"][:max(0, reserve - len(regs))]
        old_reserve = list(b["reserve_list"]) + top_up
        same_reserve = regs == b["reserve_list"] and ones == top_up
    row = {"what": "week", "date": a["date"].isoformat(), "portions": a["portions"], "by_score": a["by_score"],
           "in_turn": a["regulars_due"], "in_turn_old": b["regulars_due"],
           "same_in_turn": a["regulars_due"] == b["regulars_due"], "same_reserve": same_reserve}
    return _verdict(row, a, b["main"], old_reserve, cards)


def compare_event(a: dict, b: dict, cards: dict) -> dict:
    """One holiday list: the site's event `a` beside the desktop program's list `b`."""
    row = {"what": "event", "date": a["date"].isoformat(), "portions": a["portions"], "holiday": a["holiday"],
           "balance": a["balance"], "filtered": bool(a["criteria"]), "marked": a["marked"], "eligible": a["eligible"],
           "same_reserve": guids(a["reserve_list"]) == b["reserve_list"] and a["date"] == b["date"]}
    return _verdict(row, a, b["main"], b["reserve_list"], cards)


def compare_line(mine: dict, theirs: dict, reserve: int, cards: dict) -> list:
    """Every round of one laid-out line, in date order (an event before the week it precedes)."""
    rows = [compare_week(a, b, reserve, cards) for a, b in zip(mine["weeks"], theirs["weeks"])]
    rows += [compare_event(a, b, cards) for a, b in zip(mine["events"], theirs["events"])]
    if len(mine["weeks"]) != len(theirs["weeks"]) or len(mine["events"]) != len(theirs["events"]):
        raise RuntimeError("the two programs did not lay out the same number of rounds")
    rows.sort(key=lambda r: (r["date"], r["what"] == "week"))
    return rows


# ── the whole comparison ──────────────────────────────────────────────────────
def desktop_marked(both: Both, start, probe: dict, portions: int, reserve: int) -> int:
    """How many people the desktop program puts on a holiday list that has a portion for
    everybody who is marked for the holidays."""
    laid = both.desktop(start, 1, portions, reserve, events=[probe])["events"]
    return len(laid[0]["main"]) if laid else 0


def marks_agree(site: int, desktop: int) -> bool:
    """The two programs must find the same number of people marked for the holidays."""
    return site == desktop


def saved_filter_of(both: Both):
    """The thresholds that are saved in the desktop program (its last 'סינון מותאם'), as an
    event's filter — or None when there are none / they are not thresholds the site knows."""
    raw = both.saved_filter or {}
    fields = {f for f, _label in selection.FILTER_FIELDS}
    crit = {k: v for k, v in raw.items()
            if k in fields and isinstance(v, dict) and (v.get("min") is not None or v.get("max") is not None)}
    if not crit:
        return None
    try:
        return event_service.clean_criteria(crit)
    except Refused:
        return None


def run(src: str, work: str, now: datetime, *, weeks: int = 13, portions: int = None, reserve: int = None,
        start: date = None, sent_path: str = None, quick: bool = False, say=print) -> dict:
    """Lay everything out in both programs and compare. Returns the result — numbers and
    fixed words only (see PRIVACY above)."""
    portions = config.DEFAULT_PORTIONS if portions is None else portions
    reserve = config.DEFAULT_RESERVE if reserve is None else reserve
    start = start or service.current_week(now)
    snap = os.path.join(work, f"snapshot-{uuid.uuid4().hex[:8]}", "data.db")
    snapshot(src, snap)
    both = Both(snap, work, now, sent_path)
    sections = []

    def section(key, title, note, rows, expected=False):
        differ = sum(1 for r in rows if not r["same"])
        sections.append({"key": key, "title": title, "note": note, "rows": rows, "expected": expected,
                         "lists": len(rows), "differ": differ})
        say(f"  {key:<22} {len(rows):>3} lists, {differ} differ{'  (expected: the decision of 26/11/2026)' if expected and differ else ''}")

    def weeks_section(key, title, note, n, scored=False, as_it_is=False):
        marked = [start + timedelta(days=7 * i) for i in range(weeks)] if scored else []
        mine = both.site(start, weeks, n, reserve, scored=marked)
        theirs = both.desktop(start, weeks, n, reserve, scored=marked, as_it_is=as_it_is)
        section(key, title, note, compare_line(mine, theirs, reserve, both.cards), expected=as_it_is)
        return mine

    say(f"comparing {weeks} weeks from {start.isoformat()} ({portions} portions, {reserve} on the reserve)")
    first = weeks_section("ordinary", "שבועות רגילים",
                          f"{weeks} שבועות קדימה, {portions} מנות ו־{reserve} ברזרבה בכל שבוע.", portions)
    dues = [w["regulars_due"] for w in first["weeks"] if w["regulars_due"] > 0]
    short = max(1, int(min(dues) * 0.6)) if dues else 0
    if short:
        weeks_section("short", "כשאין מנה לכל קבוע",
                      f"אותם שבועות עם {short} מנות בלבד: פחות מהקבועים שתורם הגיע, כך שרואים מי נחתך.", short)
        weeks_section("scored", "שבוע \"לפי ניקוד\"",
                      f"אותם שבועות עם {short} מנות, כשכל שבוע מסומן \"לפי ניקוד\".", short, scored=True)
    weeks_section("as_it_is", "מול התוכנה הישנה בדיוק כמו שהיא היום",
                  "בתוכנה הישנה חד־פעמי שקיבל מנת חג או בונוס נכנס להפסקה. באתר, לפי ההכרעה שלך, חג לא נספר.",
                  portions, as_it_is=True)

    # a holiday list for every holiday somebody is marked for
    day = start + timedelta(days=4)                              # the Sunday after the first Wednesday
    hol_weeks = min(weeks, HOLIDAY_WEEKS)
    saved = saved_filter_of(both)
    codes = [c["code"] for c in event_service.holiday_choices()]
    # who is marked for the holidays at all — asked of BOTH programs, so that "the site sees
    # nobody" is never taken for "there is nobody" (the lists below are laid out only for the
    # holidays the site finds somebody for). The report always says what was found.
    probe = {"guid": "probe", "date": day, "holiday": selection.HOLIDAY_ANY, "criteria": {}, "portions": FAR,
             "reserve": 0, "balance": False, "created_at": "2026-01-01 00:00:00"}
    on_site = both.site(start, 1, portions, reserve, events=[probe])["events"]
    marked = {"site": len(on_site[0]["main"]) if on_site else 0,
              "desktop": desktop_marked(both, start, probe, portions, reserve)}
    marked["same"] = marks_agree(marked["site"], marked["desktop"])
    say(f"  marked for the holidays: the site finds {marked['site']}, the desktop program {marked['desktop']}")
    for code in codes[:1] if quick else codes:
        def event(n, **kw):
            return dict({"guid": "check", "date": day, "holiday": code, "criteria": {}, "portions": n,
                         "reserve": HOLIDAY_RESERVE, "balance": False, "created_at": "2026-01-01 00:00:00"}, **kw)
        all_in = both.site(start, 1, portions, reserve, events=[event(FAR)])["events"]
        eligible = all_in[0]["eligible"] if all_in else 0
        if not eligible:
            continue
        name = "כל נתמכי החגים" if code == selection.HOLIDAY_ANY else code
        variants = [("רגילה", {})]
        if code == selection.HOLIDAY_ANY or not quick:
            variants.append(("עם איזון בין הקהילות", {"balance": True}))
        if saved and code == selection.HOLIDAY_ANY:
            variants.append(("עם הסינון ששמור בתוכנה הישנה", {"criteria": saved}))
            variants.append(("עם הסינון ששמור בתוכנה הישנה, ועם איזון", {"criteria": saved, "balance": True}))
        for label, kw in variants:
            ev = event(max(1, eligible // 2), **kw)
            mine = both.site(start, hol_weeks, portions, reserve, events=[ev])
            theirs = both.desktop(start, hol_weeks, portions, reserve, events=[ev])
            section(f"holiday:{len(sections)}", f"חלוקת חג ({name}), {label}",
                    f"חלוקת חג ביום ראשון {day.strftime('%d/%m/%Y')} עם מנות לחצי מהמתאימים, "
                    f"ו־{hol_weeks} השבועות שסביבה.",
                    compare_line(mine, theirs, reserve, both.cards))

    real = [s for s in sections if not s["expected"]]
    lists = sum(s["lists"] for s in real)
    differ = sum(s["differ"] for s in real)
    expected = sum(s["differ"] for s in sections if s["expected"])
    rep = both.import_report
    return {
        "made_at": now.strftime("%Y-%m-%d %H:%M"),
        "source_changed_at": datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d %H:%M"),
        "start": start.isoformat(), "weeks": weeks, "portions": portions, "reserve": reserve, "quick": quick,
        "data": {k: rep.get(k, 0) for k in ("cards", "active", "history_rows", "batches", "sent_lists",
                                             "one_time_first_or_second_priority", "not_taking_part")},
        "regulars": dict(rep.get("regulars_by_frequency") or {}),
        "last_date_check": dict(rep.get("last_date_check") or {}),
        "sections": sections, "lists": lists, "differ": differ, "identical": differ == 0 and marked["same"],
        "holiday_marked": marked,
        "expected_differences": expected,
        # a difference against the program "as it is" is the decision's doing only when the
        # same weeks match once the decision is applied on both sides
        "expected_explained": expected == 0 or next(s for s in sections if s["key"] == "ordinary")["differ"] == 0,
    }


# ── the report ────────────────────────────────────────────────────────────────
_CSS = """
:root { --bg:#f4f7f6; --surface:#fff; --fg:#17221e; --muted:#5b6a64; --line:#dbe3e0; --ok:#0b7d5f; --soft:#e3f3ed;
        --warn-bg:#fff3d6; --warn-fg:#7a4d00; }
@media (prefers-color-scheme: dark) { :root { --bg:#111816; --surface:#1a2320; --fg:#e5eeea; --muted:#9aaaa3;
        --line:#2b3732; --ok:#3cc9a0; --soft:#173a30; --warn-bg:#3d3012; --warn-fg:#ffd88a; color-scheme: dark; } }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 56px; background:var(--bg); color:var(--fg);
       font-family:"Segoe UI","Heebo",Arial,sans-serif; font-size:16px; line-height:1.55; }
.wrap { max-width:980px; margin:0 auto; display:flex; flex-direction:column; gap:18px; }
h1 { margin:0; font-size:1.9rem; } h2 { margin:0; font-size:1.2rem; } p { margin:0; }
.sub { color:var(--muted); font-size:.92rem; }
.verdict { border-radius:14px; padding:18px 20px; font-size:1.35rem; font-weight:700; }
.verdict.ok { background:var(--soft); color:var(--ok); } .verdict.bad { background:var(--warn-bg); color:var(--warn-fg); }
.verdict small { display:block; font-size:.95rem; font-weight:400; color:var(--fg); margin-top:4px; }
.tiles { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.tile { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 14px; }
.tile b { display:block; font-size:1.9rem; line-height:1.1; font-variant-numeric:tabular-nums; }
.tile span { color:var(--muted); font-size:.88rem; }
section { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px;
          display:flex; flex-direction:column; gap:10px; }
.head { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; justify-content:space-between; }
.tag { border-radius:999px; padding:2px 12px; font-size:.86rem; font-weight:700; white-space:nowrap; }
.tag.ok { background:var(--soft); color:var(--ok); } .tag.bad, .tag.note { background:var(--warn-bg); color:var(--warn-fg); }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { text-align:start; padding:5px 9px; border-bottom:1px solid var(--line); white-space:nowrap; }
thead th { color:var(--muted); font-size:.86rem; font-weight:600; }
td.yes { color:var(--ok); font-weight:700; } td.no { color:var(--warn-fg); background:var(--warn-bg); font-weight:700; }
tr.diff td { white-space:normal; background:var(--bg); font-size:.93rem; }
tr.diff ul { margin:4px 0; padding-inline-start:20px; }
.scroll { overflow-x:auto; }
.box { background:var(--soft); border-radius:10px; padding:12px 14px; display:flex; flex-direction:column; gap:5px; }
.box.note { background:var(--warn-bg); color:var(--warn-fg); }
"""


def _e(x) -> str:
    return html.escape(str(x))


def _dmy(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{int(d)}/{int(m)}/{y}"


def _stamp(text: str) -> str:
    return f"{_dmy(text)} בשעה {text[11:16]}"


def _count(n: int, one: str, many: str) -> str:
    return one if n == 1 else f"{n} {many}"


def _mark(ok: bool) -> str:
    return '<td class="yes">כן</td>' if ok else '<td class="no">לא</td>'


def _difference_lines(row: dict) -> str:
    lines = []
    if not row.get("same_in_turn", True):
        lines.append(f"קבועים שתורם הגיע: באתר {row['in_turn']}, בתוכנה הישנה {row['in_turn_old']}.")
    if row["main"] != row["main_old"]:
        lines.append(f"ברשימה: באתר {row['main']}, בתוכנה הישנה {row['main_old']}.")
    if row["first_out_of_order"]:
        lines.append(f"אותם אנשים, אבל הסדר שונה החל מהמקום ה־{row['first_out_of_order']}.")
    kinds = {}                                              # the same words once, with how many people they are true of
    for d in row["differences"]:
        key = (d["who"], d["site"], d["why"], d["old"])
        kinds[key] = kinds.get(key, 0) + 1
    items = [f"{_e(who)}{f' ({n})' if n > 1 else ''}: באתר {PLACE[site]}{' (' + _e(why) + ')' if why else ''}, "
             f"בתוכנה הישנה {PLACE[theirs]}." for (who, site, why, theirs), n in list(kinds.items())[:SHOWN]]
    more = len(kinds) - SHOWN
    if more > 0:
        items.append(f"ועוד {_count(more, 'סוג אחד', 'סוגים')} של הבדל.")
    out = "".join(f"<p>{_e(ln)}</p>" for ln in lines)
    if items:
        out += "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"
    return out or "<p>יש הבדל ברזרבה בלבד.</p>"


def _section_html(s: dict, explained: bool) -> str:
    if not s["differ"]:
        tag = f'<span class="tag ok">זהה · {_count(s["lists"], "רשימה אחת", "רשימות")}</span>'
    elif s["expected"]:
        tag = f'<span class="tag note">הבדל צפוי ב־{_count(s["differ"], "רשימה אחת", "רשימות")}</span>'
    else:
        tag = f'<span class="tag bad">הבדל ב־{s["differ"]} מתוך {s["lists"]}</span>'
    body = []
    for r in s["rows"]:
        if r["what"] == "week":
            what = "שבוע" + (" · לפי ניקוד" if r["by_score"] else "")
            turn = str(r["in_turn"])
        else:
            what = "חלוקת חג" + (" · איזון" if r["balance"] else "") + (" · סינון" if r["filtered"] else "")
            turn = f"{r['eligible']} מתאימים"
        body.append(f"<tr><td>{_dmy(r['date'])}</td><td>{_e(what)}</td><td>{r['portions']}</td><td>{_e(turn)}</td>"
                    f"<td>{r['main']}</td><td>{r['reserve']}</td>{_mark(r['same_people'])}{_mark(r['same_order'])}"
                    f"{_mark(r['same_reserve'])}</tr>")
        if not r["same"]:
            body.append(f'<tr class="diff"><td colspan="9">{_difference_lines(r)}</td></tr>')
    note = ""
    if s["expected"] and s["differ"]:
        note = ('<div class="box note"><p><b>זה ההבדל שההכרעה שלך יוצרת, ולא תקלה.</b> כשמחילים את ההכרעה גם על התוכנה '
                'הישנה ("שבועות רגילים" למעלה), הרשימות זהות.</p></div>' if explained else
                '<div class="box note"><p><b>אי אפשר לייחס את ההבדל הזה להכרעה בלבד,</b> כי גם "שבועות רגילים" למעלה '
                'לא יצאו זהים.</p></div>')
    return (f'<section><div class="head"><h2>{_e(s["title"])}</h2>{tag}</div><p class="sub">{_e(s["note"])}</p>{note}'
            '<div class="scroll"><table><thead><tr><th>תאריך</th><th>מה</th><th>מנות</th><th>קבועים שתורם הגיע</th>'
            '<th>ברשימה</th><th>ברזרבה</th><th>אותם אנשים</th><th>אותו סדר</th><th>אותה רזרבה</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></section>')


def _holiday_note(r: dict) -> str:
    """What was found about the holiday lists when there is no list to show for them."""
    m = r["holiday_marked"]
    if not m["same"]:
        return ('<section><div class="head"><h2>חלוקות חג</h2><span class="tag bad">הבדל</span></div>'
                f'<p>מי שמסומן "נתמך חגים": האתר מוצא {m["site"]}, והתוכנה הישנה {m["desktop"]}. '
                'המספרים האלה צריכים להיות שווים.</p></section>')
    if not m["site"]:
        return ('<section><div class="head"><h2>חלוקות חג</h2><span class="tag note">לא הושוו</span></div>'
                '<p>אף כרטיס פעיל לא מסומן "נתמך חגים", לא באתר ולא בתוכנה הישנה. רשימת חג יוצאת ריקה בשתיהן, '
                'ולכן אין מה להשוות. אחרי שיסומנו מקבלים לחג, כדאי להריץ את ההשוואה שוב.</p></section>')
    return ""


def render(result: dict) -> str:
    """The report as one self-contained page (numbers and fixed words only)."""
    r = result
    if r["identical"]:
        verdict = (f'<div class="verdict ok">האתר והתוכנה הישנה נותנים אותן רשימות'
                   f'<small>{_count(r["lists"], "רשימה אחת נבדקה", "רשימות נבדקו")}: אותם אנשים, באותו סדר, ואותה רזרבה.</small></div>')
    elif not r["differ"]:
        verdict = ('<div class="verdict bad">הרשימות זהות, אבל לא אותם אנשים מסומנים לחג'
                   f'<small>האתר מוצא {r["holiday_marked"]["site"]} מסומנים "נתמך חגים", והתוכנה הישנה '
                   f'{r["holiday_marked"]["desktop"]}. עד שזה מוסבר, לא לסמוך על רשימות החג של האתר.</small></div>')
    else:
        verdict = (f'<div class="verdict bad">יש הבדל ב־{r["differ"]} מתוך {r["lists"]} רשימות'
                   '<small>הפירוט למטה, בכל רשימה שיצאה שונה. עד שזה מוסבר, לא לסמוך על האתר בנתונים האלה.</small></div>')
    d = r["data"]
    tiles = "".join(f'<div class="tile"><b>{_e(v)}</b><span>{_e(label)}</span></div>' for v, label in (
        (r["lists"], "רשימות נבדקו"), (r["lists"] - r["differ"], "יצאו זהות"), (r["differ"], "יצאו שונות"),
        (d["active"], f"מקבלים פעילים, מתוך {d['cards']} כרטיסים")))
    regs = " · ".join(f"{_e(k)}: {v}" for k, v in r["regulars"].items()) or "אין"
    return f"""<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>השוואה מול התוכנה הישנה</title><style>{_CSS}</style></head><body><div class="wrap">
<header><h1>השוואה בין האתר לתוכנה הישנה</h1>
<p class="sub">נוצר ב־{_stamp(r["made_at"])}, על עותק של הנתונים (הקובץ השתנה לאחרונה ב־{_stamp(r["source_changed_at"])}).
הנתונים עצמם לא שונו: הקובץ רק נקרא, והכול נעשה על עותקים שנמחקו בסוף.</p></header>
{verdict}
<div class="tiles">{tiles}</div>
<div class="box"><p><b>מה יש בנתונים:</b> קבועים לפי תדירות: {regs}. חד־פעמיים בעדיפות ראשונה או שנייה:
{d["one_time_first_or_second_priority"]}. רישומים בהיסטוריה: {d["history_rows"]}.</p>
<p><b>מה הושווה:</b> {r["weeks"]} שבועות החל מ־{_dmy(r["start"])}, {r["portions"]} מנות ו־{r["reserve"]} ברזרבה
בשבוע רגיל{" (הרצה מקוצרת)" if r["quick"] else ""}.</p></div>
{"".join(_section_html(s, r["expected_explained"]) for s in r["sections"])}
{_holiday_note(r)}
<section><h2>מה לא הושווה, ולמה</h2>
<p>נעילת רשימות, רישום "הגיע / לא הגיע", ו"סינון מותאם" לשבוע רגיל: אלה קיימים רק בתוכנה הישנה, ובאתר אין להם מקבילה.</p>
<p>שינויים ביד (הוספה, רזרבה, הסרה): הם תלויים במה שהמנהל בוחר, ולכן נבדקים בבדיקות של האתר ולא כאן.</p></section>
<p class="sub">בדוח הזה אין שמות, טלפונים או פרטים מזהים: רק מספרים, תאריכים וסוגי מקבלים. מותר להעביר אותו הלאה.</p>
</div></body></html>
"""


def render_failure(now: datetime, error: str) -> str:
    return f"""<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><title>ההשוואה לא רצה</title><style>{_CSS}</style></head>
<body><div class="wrap"><h1>ההשוואה לא רצה</h1>
<div class="verdict bad">משהו עצר את ההשוואה לפני שהיא הסתיימה<small>הנתונים לא שונו. אם התוכנה הישנה פתוחה, כדאי לסגור אותה ולהריץ שוב. אם זה חוזר, להעביר את השורה שלמטה למי שבנה את האתר.</small></div>
<section><p class="sub">{_e(now.strftime("%Y-%m-%d %H:%M"))}</p><p dir="ltr">{_e(error)}</p></section></div></body></html>
"""


# ── the command line ──────────────────────────────────────────────────────────
def default_report_path(now: datetime) -> str:
    return os.path.join(config.data_dir(), "compare", f"compare-{now.strftime('%Y%m%d-%H%M')}.html")


def main(argv=None) -> int:
    """0 = the same lists, 1 = differences, 2 = the comparison could not run."""
    ap = argparse.ArgumentParser(description="Compare the website with the desktop program on a copy of real data.")
    ap.add_argument("--from", dest="src", required=True, help="the data.db to compare on (it is only read)")
    ap.add_argument("--sent-history", help="json of lists that were already sent (taken as received)")
    ap.add_argument("--weeks", type=int, default=13)
    ap.add_argument("--portions", type=int, default=config.DEFAULT_PORTIONS)
    ap.add_argument("--reserve", type=int, default=config.DEFAULT_RESERVE)
    ap.add_argument("--start", help="the first Wednesday (default: the week being prepared now)")
    ap.add_argument("--report", nargs="?", const="", default=None,
                    help="write the report as a page (default place: <the site's data folder>/compare/)")
    ap.add_argument("--open", action="store_true", help="open the report in the browser")
    ap.add_argument("--quick", action="store_true", help="one holiday only")
    args = ap.parse_args(argv)

    now = config.now()
    report_path = None if args.report is None else (args.report or default_report_path(now))
    work = tempfile.mkdtemp(prefix="haluka_real_check_")
    os.environ["HALUKA_WEB_SKIP_GIT_GUARD"] = "1"            # the temp folder is not a repository
    result, error = None, ""
    try:
        if not 1 <= args.weeks <= 104 or args.portions < 1 or args.reserve < 0:
            raise ValueError("weeks must be 1-104, portions at least 1, reserve 0 or more")
        result = run(args.src, work, now, weeks=args.weeks, portions=args.portions, reserve=args.reserve,
                     start=date.fromisoformat(args.start) if args.start else None,
                     sent_path=args.sent_history, quick=args.quick)
    except Exception as e:                                   # whatever stopped it: say so, change nothing
        error = f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if os.path.exists(work):
            print(f"WARNING: the temp folder could not be removed — delete it by hand: {work}")

    if report_path:
        os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(render(result) if result else render_failure(now, error))
        print(f"report: {report_path}")
        if args.open:
            webbrowser.open(pathlib.Path(report_path).resolve().as_uri())
    if result is None:
        print(f"\nRESULT: the comparison COULD NOT RUN — {error}")
        return 2
    print(f"\nRESULT: {result['lists']} lists compared, {result['differ']} differ"
          + (f"; {result['expected_differences']} more differ from the desktop program as it is today "
             "(expected: a holiday portion does not count on the site)" if result["expected_differences"] else ""))
    m = result["holiday_marked"]
    print(f"        marked for the holidays: the site finds {m['site']}, the desktop program {m['desktop']}"
          + ("" if m["same"] else "  <- THESE MUST BE EQUAL")
          + ("  (nobody is marked: no holiday list to compare)" if m["same"] and not m["site"] else ""))
    print("        " + ("the site and the desktop program give the SAME lists on this data"
                         if result["identical"] else "DIFFERENCES found — do not trust the site on this data yet"))
    return 0 if result["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
