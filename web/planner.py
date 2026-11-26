# -*- coding: utf-8 -*-
"""Forward planner — "the past is fixed, the future is always computed".

Pure: no database, no clock, no web. Given the recipients as they are NOW, the received
history and the settings, it lays out the list of each coming Wednesday in turn. After
each week everybody on the MAIN list is taken as having received (decision 25/11/2026:
the plan is the record, nobody ticks who came), so the next week sees the consequences —
turns by frequency, the one-timers' pause, one portion per week.

WHO receives is decided by the existing engine (selection.py / scoring.py), untouched.
This module only
  1. prepares each person's row the way the desktop program's database layer did
     (derived last / next dates, waiting days, the rule-9 tag), and
  2. calls the engine in the order the desktop screen did in its regular ('schedule')
     mode: regulars whose turn has come -> cut to the portions by who waited longest ->
     the remaining portions go to the one-timers' queue -> reserve after them.

web/tests/test_vs_old.py runs this side by side with the desktop program's own code on
random data and requires the same lists, week after week.

Stage 4 — a HOLIDAY EVENT is one more round on the same time line (plan_timeline). It is
an EXTRA round, exactly as in the desktop program: everybody marked "נתמך חגים" for that
holiday who passes the event's filter, whatever his kind and whatever his turn (the turn
gates are skipped); short of portions -> whoever waited longest. It never moves a
regular's turn, but it does count as "received" — so a one-timer who got a holiday portion
starts his pause, and everybody's waiting days start again. That is why the weeks after an
event depend on it, and why events are laid out in date order together with the weeks.
"""
import re
from bisect import bisect_left
from datetime import date, timedelta

from .engine import holidays, scoring, selection

_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

ACTIVE = "פעיל"
ONE_TIME = "חד-פעמי"
ROLE_MAIN, ROLE_RESERVE, ROLE_OUT = selection.ROLE_MAIN, selection.ROLE_RESERVE, selection.ROLE_OUT

KIND_REGULAR, KIND_ONE_TIME = "regular", "onetime"
KIND_OTHER = "other"           # a card that takes no part in the weekly lists (holiday events only)
# Why somebody is not on a week's list — the third column of the screen, by reason.
OUT_REG_WAIT = "reg_wait"      # a regular whose turn has not come (rule 6) / served this week (rule 9)
OUT_REG_CUT = "reg_cut"        # a regular whose turn came but the portions ran out (rule 8)
OUT_ONE_PAUSE = "one_pause"    # a one-timer inside the pause after receiving (rule 7)
OUT_ONE_QUEUE = "one_queue"    # a one-timer waiting in the queue, portions and reserve are full
OUT_NO_PORTIONS = "no_portions"
OUT_REMOVED = "removed"        # taken off this week's list by hand
# ...and why somebody marked for the holidays is not on a holiday event's list.
OUT_EV_MISSING = "ev_missing"  # a field the event filters by has no value on his card
OUT_EV_CUT = "ev_cut"          # passes the filter, but the portions and the reserve ran out
OUT_EV_FILTER = "ev_filter"    # outside the event's filter
OUT_EV_OTHER = "ev_other"      # marked for other holidays only
# What the manager can set by hand for one person in one week.
MANUAL_ADD, MANUAL_RESERVE, MANUAL_REMOVE = "add", "reserve", "remove"
MANUAL_ACTIONS = (MANUAL_ADD, MANUAL_RESERVE, MANUAL_REMOVE)

PRIORITY_LABEL = {3: "עדיפות ראשונה", 2: "עדיפות שנייה"}

# Mirror of database.EXTRA_BY_WEEKDAY_BEFORE: until that day a Sunday–Tuesday round was an
# EXTRA one automatically; from it on a round is extra only when it is marked (holiday /
# bonus, carried in the `holiday` field). An extra round never moves the regular turn.
EXTRA_BY_WEEKDAY_BEFORE = "2026-10-18"


# ── small pure helpers ────────────────────────────────────────────────────────
def valid_iso(s) -> str:
    """'YYYY-MM-DD' when `s` is exactly a real ISO date, else '' (junk never competes)."""
    s = (s or "").strip() if isinstance(s, str) else ""
    if not _ISO_RE.fullmatch(s):
        return ""
    try:
        date.fromisoformat(s)
    except ValueError:
        return ""
    return s


def to_date(s):
    s = valid_iso(s)
    return date.fromisoformat(s) if s else None


def is_extra_round(dist_date: str, holiday: str) -> bool:
    """A round that does not move the regular turn: holiday / bonus (any `holiday` mark),
    or — before the cut-over day — any Sunday–Tuesday round."""
    if (holiday or "").strip():
        return True
    d = to_date(dist_date)
    return bool(d and d.weekday() in (6, 0, 1) and dist_date < EXTRA_BY_WEEKDAY_BEFORE)


def recency_days(rec: dict, today: date) -> int:
    """Waiting days for the ranking: since the last distribution; somebody who never
    received counts from registration (start_date, else created_at). Never negative.
    Same rule as the desktop program's database.recency_days."""
    for key in ("last_distribution", "start_date", "created_at"):
        s = str(rec.get(key) or "").strip()
        if not s:
            continue
        try:
            d = date.fromisoformat(s[:10])
        except ValueError:
            continue
        return max(0, (today - d).days)
    return 0


def need_weights(settings: dict) -> dict:
    """The need-score weights from the settings (need_w_<factor>), with the engine's
    defaults for anything missing or invalid; negatives count as 0."""
    out = {}
    for f in scoring.NEED_FACTORS:
        raw = (settings or {}).get("need_w_" + f["key"])
        try:
            w = float(raw)
            w = 0.0 if w < 0 else w
        except (TypeError, ValueError):
            w = scoring.DEFAULT_NEED_WEIGHTS.get(f["key"], 0.0)
        out[f["key"]] = w
    return out


def is_active(rec: dict) -> bool:
    return (rec.get("status") or "") == ACTIVE


def participation(rec: dict) -> str:
    """'regular' / 'onetime' for people the lists are built from, '' for a card that is
    data only (no frequency, or a one-timer without a first / second priority)."""
    if selection.is_regular(rec):
        return KIND_REGULAR
    if selection.is_one_time_candidate(rec):
        return KIND_ONE_TIME
    return ""


def why_not_participating(rec: dict) -> str:
    if not is_active(rec):
        return "מושהה · לא נכנס לרשימות עד שיחזור להיות פעיל"
    if (rec.get("frequency") or "") == ONE_TIME:
        return "חד-פעמי בלי עדיפות ראשונה או שנייה · לא נכנס לרשימות אוטומטית"
    return "כרטיס בלי תדירות · לא נכנס לרשימות אוטומטית"


# ── who received what, when ───────────────────────────────────────────────────
class Ledger:
    """Received rounds per person: the real history plus the weeks already laid out.

    `horizon` is the upcoming Wednesday as of today: a history date after it is a typing
    mistake and is ignored (decision 27/9/2026) — the person is simply due."""

    def __init__(self, horizon: date):
        self.horizon = horizon
        self._any = {}        # guid -> latest received round of any kind
        self._reg = {}        # guid -> sorted list of REGULAR received rounds

    def load(self, rows) -> "Ledger":
        """`rows`: history rows (dicts) with recipient_guid, dist_date, received, holiday."""
        for row in rows:
            if not row.get("received"):
                continue                      # a recorded no-show received nothing
            guid = row.get("recipient_guid")
            raw = row.get("dist_date")
            iso = valid_iso(raw) if isinstance(raw, str) and len(raw) == 10 else ""
            if not guid or not iso:
                continue
            d = date.fromisoformat(iso)
            if d > self.horizon:
                continue
            self._put(guid, d, is_extra_round(iso, row.get("holiday") or ""))
        for lst in self._reg.values():
            lst.sort()
        return self

    def _put(self, guid, d, extra):
        if guid not in self._any or d > self._any[guid]:
            self._any[guid] = d
        if not extra:
            self._reg.setdefault(guid, []).append(d)

    def add_regular(self, guid: str, wed: date):
        """A laid-out week: `guid` is on the MAIN list of `wed` and counts as received."""
        if guid not in self._any or wed > self._any[guid]:
            self._any[guid] = wed
        lst = self._reg.setdefault(guid, [])
        if lst and wed < lst[-1]:
            lst.insert(bisect_left(lst, wed), wed)
        else:
            lst.append(wed)

    def add_extra(self, guid: str, day: date):
        """A laid-out HOLIDAY event: `guid` is on its MAIN list and counts as received on
        `day` — in an extra round. It is his last distribution from now on (waiting days,
        a one-timer's pause), but never a regular round: a regular's turn does not move."""
        if guid not in self._any or day > self._any[guid]:
            self._any[guid] = day

    def last_any(self, guid):
        return self._any.get(guid)

    def last_regular(self, guid):
        lst = self._reg.get(guid)
        return lst[-1] if lst else None

    def regular_between(self, guid, lo: date, hi: date) -> bool:
        lst = self._reg.get(guid)
        if not lst:
            return False
        i = bisect_left(lst, lo)
        return i < len(lst) and lst[i] <= hi


def _later(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _last_dates(rec: dict, ledger: Ledger) -> tuple:
    """(last round of ANY kind, last REGULAR round, the imported base date) of one card.
    The base — a "last distribution" that came with an import, with no history row behind
    it — counts like a regular round; one dated after the horizon is a typing mistake."""
    guid = rec.get("guid")
    base = to_date(rec.get("last_dist_base"))
    if base is not None and base > ledger.horizon:
        base = None
    return _later(ledger.last_any(guid), base), _later(ledger.last_regular(guid), base), base


def week_row(rec: dict, wed: date, ledger: Ledger) -> dict:
    """A copy of the card with the fields the engine reads, as they stand for the week of
    `wed`: last_distribution (any round), next_distribution (from the last REGULAR round),
    round_served (rule 9) and days_since. The card itself is never modified."""
    row = dict(rec)
    guid = rec.get("guid")
    last_any, last_reg, base = _last_dates(rec, ledger)
    row["last_distribution"] = last_any.isoformat() if last_any else ""
    row["next_distribution"] = ""
    row.pop("round_served", None)
    row.pop("planned_elsewhere", None)        # the site has no locked lists (decision 25/11/2026)
    if selection.is_regular(row):
        freq = (row.get("frequency") or "").strip()
        if freq in selection.FREQUENCY_INTERVAL_DAYS:
            # No regular round behind him (never served, or extra rounds only) -> due now.
            row["next_distribution"] = (selection.next_due(last_reg.isoformat(), freq, wed)
                                        if last_reg else wed).isoformat()
        lo = wed - timedelta(days=selection.ROUND_WINDOW_DAYS)
        row["round_served"] = (ledger.regular_between(guid, lo, wed)
                               or (base is not None and lo <= base <= wed))
    row["days_since"] = recency_days(row, wed)
    return row


def event_row(rec: dict, day: date, ledger: Ledger) -> dict:
    """A copy of the card as it stands on the day of a holiday event. A holiday round
    skips the turn gates (rules 6, 7, 9), so only two things are read from the past: the
    last distribution of any kind, and the waiting days counted from it."""
    row = dict(rec)
    last_any, _last_reg, _base = _last_dates(rec, ledger)
    row["last_distribution"] = last_any.isoformat() if last_any else ""
    row["next_distribution"] = ""
    row.pop("round_served", None)
    row.pop("planned_elsewhere", None)
    row["days_since"] = recency_days(row, day)
    return row


# ── the explanations shown on the screen ──────────────────────────────────────
def _dm(d: date) -> str:
    return d.strftime("%d/%m")


def _freq_label(row: dict) -> str:
    return (row.get("frequency") or "").strip() or "קבוע"


def _last_text(row: dict) -> str:
    d = to_date(row.get("last_distribution"))
    return f"קיבל לאחרונה ב-{_dm(d)}" if d else "עוד לא קיבל אף פעם"


def _entry(row: dict, kind: str, role: str, why: str, **extra) -> dict:
    score = row.get("need_score")
    e = {
        "guid": row.get("guid"), "name": row.get("full_name") or "", "kind": kind,
        "freq": (row.get("frequency") or "").strip(), "priority": row.get("priority"),
        "role": role, "why": why,
        "last": row.get("last_distribution") or "", "days_since": row.get("days_since") or 0,
        "score": round(score, 1) if isinstance(score, (int, float)) else None,
    }
    e.update(extra)
    return e


# ── one week ──────────────────────────────────────────────────────────────────
def _kind(row: dict) -> str:
    return KIND_REGULAR if selection.is_regular(row) else KIND_ONE_TIME


def plan_week(wed: date, people: list, ledger: Ledger, *, portions: int, reserve: int,
              weights: dict, cooldown_weeks: int, manual: dict = None) -> dict:
    """The list of the Wednesday `wed`. `people`: active cards, ordered by name.
    Returns main / reserve_list / out (entries with a Hebrew 'why') and the week's numbers.
    Nothing is recorded here — plan_weeks() does that between weeks.

    `manual` = what the manager set by hand for THIS week, {guid: 'add' | 'reserve' |
    'remove'} (decision 25/11/2026: it stays while everything around it is recomputed):
      add     — on the MAIN list whatever his turn; he takes a portion and counts as having
                received, so his turn is counted from this week.
      reserve — on the reserve, first in line; did not receive, keeps his turn.
      remove  — on no list this week; did not receive, keeps his turn.
    A regular added by hand takes a portion from the one-timers first and pushes a regular
    out only when the regulars alone exceed the portions; a one-timer added by hand never
    pushes a regular out (the engine's rule 8) — the list is then longer, with a warning."""
    portions = max(0, int(portions or 0))
    reserve = max(0, int(reserve or 0))
    manual = manual or {}
    by_hand = {MANUAL_ADD: [], MANUAL_RESERVE: [], MANUAL_REMOVE: []}
    for p in people:
        action = manual.get(p.get("guid"))
        if action in by_hand:
            by_hand[action].append(week_row(p, wed, ledger))
    free = [p for p in people if manual.get(p.get("guid")) not in by_hand]
    regs = [week_row(p, wed, ledger) for p in free if selection.is_regular(p)]
    ones = [week_row(p, wed, ledger) for p in free if selection.is_one_time_candidate(p)]

    main, reserve_list, out, warnings = [], [], [], []
    for r in by_hand[MANUAL_REMOVE]:
        out.append(_entry(r, _kind(r), ROLE_OUT,
                          "הוסר ביד מהשבוע הזה · לא נחשב כמי שקיבל, והתור שלו נשאר",
                          group=OUT_REMOVED, manual=MANUAL_REMOVE, sort=("", r.get("full_name") or "")))

    # 1. Regulars whose turn has come (rules 6 + 9 — the engine's single gate).
    due = [r for r in regs if selection.is_due(r, wed, cooldown_weeks)]
    due_ids = {id(r) for r in due}
    regs_due = len(due)
    for r in regs:
        if id(r) not in due_ids:
            turn = to_date(r.get("next_distribution"))
            out.append(_entry(r, KIND_REGULAR, ROLE_OUT,
                              selection.not_due_reason(r, wed, cooldown_weeks),
                              group=OUT_REG_WAIT, sort=((turn or wed).isoformat(), r.get("full_name") or "")))

    # 2. One-timers of a first / second priority whose pause is over (rule 7).
    queue = []
    for r in ones:
        if selection.is_due(r, wed, cooldown_weeks):
            queue.append(r)
        else:
            # back on the first Wednesday after the pause, counted from his round's Wednesday
            back = (selection.round_wednesday(to_date(r["last_distribution"]))
                    + timedelta(days=7 * max(0, int(cooldown_weeks))))
            out.append(_entry(r, KIND_ONE_TIME, ROLE_OUT,
                              "חד-פעמי · " + selection.not_due_reason(r, wed, cooldown_weeks),
                              group=OUT_ONE_PAUSE, sort=(back.isoformat(), r.get("full_name") or "")))
    queue = selection.rank_one_time_priority(queue)       # fixed formula; priority first

    if portions <= 0:
        # Rule 8: no portions -> an empty list (and nobody is recorded for this week).
        warnings.append("0 מנות: הרשימה של השבוע הזה ריקה")
        for r in by_hand[MANUAL_ADD] + by_hand[MANUAL_RESERVE]:
            out.append(_entry(r, _kind(r), ROLE_OUT, "סומן ביד לשבוע הזה, אבל אין בו מנות",
                              group=OUT_NO_PORTIONS, manual=manual[r["guid"]],
                              sort=(0, r.get("full_name") or "")))
        for r in due:
            out.append(_entry(r, KIND_REGULAR, ROLE_OUT,
                              f"{_freq_label(r)} · התור שלו הגיע, אבל אין מנות בשבוע הזה",
                              group=OUT_NO_PORTIONS, sort=(0, r.get("full_name") or "")))
        for i, r in enumerate(queue):
            out.append(_entry(r, KIND_ONE_TIME, ROLE_OUT,
                              f"חד-פעמי · {PRIORITY_LABEL.get(r.get('priority'), '')} · "
                              f"מקום {i + 1} בתור · אין מנות בשבוע הזה",
                              group=OUT_NO_PORTIONS, place=i + 1, sort=(1, i)))
        return _week(wed, portions, reserve, regs_due, 0, False, main, reserve_list, out,
                     warnings, len(queue))

    # 3a. What the manager set by hand comes first.
    for r in by_hand[MANUAL_ADD]:
        main.append(_entry(r, _kind(r), ROLE_MAIN,
                           "נוסף ביד לשבוע הזה · נחשב כמי שקיבל, והתור שלו נספר מכאן",
                           manual=MANUAL_ADD))
    for r in by_hand[MANUAL_RESERVE]:
        reserve_list.append(_entry(r, _kind(r), ROLE_RESERVE,
                                   "הועבר ביד לרזרבה · נכנס אם מישהו לא מגיע, ולא נחשב כמי שקיבל",
                                   manual=MANUAL_RESERVE))
    added_regs = sum(1 for r in by_hand[MANUAL_ADD] if selection.is_regular(r))
    added_others = len(by_hand[MANUAL_ADD]) - added_regs
    reserve_auto = max(0, reserve - len(by_hand[MANUAL_RESERVE]))

    # 3. Rule 8: fewer portions than regulars in turn -> whoever waited longest.
    kept = selection.limit_due_regulars(due, weights, portions, reserve_auto, added_regs)
    cut = len(kept) < regs_due or any(r.get("_reserve") for r in kept)
    if cut:
        warnings.append(f"{regs_due} קבועים בתור ורק {portions} מנות: נכנסו מי שחיכו הכי הרבה זמן")
    reg_reserve = 0
    for r in kept:
        label = _freq_label(r)
        if r.get("_reserve"):
            reg_reserve += 1
            reserve_list.append(_entry(
                r, KIND_REGULAR, ROLE_RESERVE,
                f"{label} · התור שלו הגיע, אבל יש {regs_due} קבועים בתור ורק {portions} מנות · "
                "רזרבה: נכנס אם מישהו לא מגיע"))
        else:
            why = (f"{label} · {_last_text(r)} · התור שלו הגיע" if r.get("last_distribution")
                   else f"{label} · עוד לא קיבל אף פעם, ולכן נכנס מיד")
            if cut:
                why += f" · נכנס כי הוא מחכה {r.get('days_since') or 0} ימים, יותר מאחרים"
            main.append(_entry(r, KIND_REGULAR, ROLE_MAIN, why))
    if cut:
        dropped = [r for r in due if r.get("_role") == ROLE_OUT]
        dropped.sort(key=lambda r: (-(r.get("days_since") or 0), -(r.get("need_score") or 0),
                                    r.get("full_name") or ""))
        for i, r in enumerate(dropped):
            out.append(_entry(
                r, KIND_REGULAR, ROLE_OUT,
                f"{_freq_label(r)} · התור שלו הגיע, אבל יש {regs_due} קבועים בתור ורק {portions} מנות · "
                "לא נשאר מקום גם ברזרבה",
                group=OUT_REG_CUT, sort=("", i)))

    # 4. The portions left go to the one-timers' queue; the reserve comes right after
    #    them. Rule 3 — the reserve is always shown: when regulars already hold part of it
    #    (the cut above), the queue tops it up (same result as selection.top_up_reserve).
    slots = max(0, selection.one_time_slots(portions, regs_due, added_regs) - added_others)
    selection.assign_roles(queue, slots, max(0, reserve_auto - reg_reserve))
    n_queue = len(queue)
    for i, r in enumerate(queue):
        tier = PRIORITY_LABEL.get(r.get("priority"), "")
        head = f"חד-פעמי · {tier} · מקום {i + 1} מתוך {n_queue} בתור"
        if r["_role"] == ROLE_MAIN:
            main.append(_entry(r, KIND_ONE_TIME, ROLE_MAIN, f"{head} · {_last_text(r)}", place=i + 1))
        elif r["_role"] == ROLE_RESERVE:
            reserve_list.append(_entry(r, KIND_ONE_TIME, ROLE_RESERVE,
                                       f"{head} · רזרבה: נכנס אם מישהו לא מגיע", place=i + 1))
        else:
            out.append(_entry(r, KIND_ONE_TIME, ROLE_OUT,
                              f"{head} · המנות והרזרבה התמלאו לפניו",
                              group=OUT_ONE_QUEUE, place=i + 1, sort=("", i)))
    empty = portions - len(main)
    if empty > 0:
        warnings.append(f"{empty} מנות נשארו בלי מקבל: אין מספיק חד-פעמיים פנויים בתור")
    elif empty < 0:
        warnings.append(f"ברשימה {len(main)} מקבלים ויש רק {portions} מנות: "
                        f"{-empty} יותר מדי, בגלל הוספות ביד")
    return _week(wed, portions, reserve, regs_due, slots, cut, main, reserve_list, out,
                 warnings, n_queue)


_OUT_ORDER = {OUT_REMOVED: -1, OUT_REG_CUT: 0, OUT_NO_PORTIONS: 1, OUT_ONE_QUEUE: 2,
              OUT_REG_WAIT: 3, OUT_ONE_PAUSE: 4}


def _week(wed, portions, reserve, regs_due, slots, cut, main, reserve_list, out, warnings, n_queue):
    out.sort(key=lambda e: (_OUT_ORDER.get(e.get("group"), 9), e.pop("sort", ("",))))
    counts = {}
    for e in main:
        key = e["freq"] if e["kind"] == KIND_REGULAR else ONE_TIME
        counts[key] = counts.get(key, 0) + 1
    return {
        "date": wed, "portions": portions, "reserve": reserve,
        "regulars_due": regs_due, "one_time_slots": slots, "one_time_queue": n_queue, "cut": cut,
        "main": main, "reserve_list": reserve_list, "out": out,
        "main_regulars": sum(1 for e in main if e["kind"] == KIND_REGULAR),
        "main_one_timers": sum(1 for e in main if e["kind"] == KIND_ONE_TIME),
        "empty_portions": max(0, portions - len(main)),
        "counts": counts, "warnings": warnings,
    }


# ── one holiday event ─────────────────────────────────────────────────────────
def event_criteria(event: dict) -> dict:
    """The event's filter in the engine's own shape: the thresholds that were set, and the
    holiday gate — which is always on (an event that names no holiday takes everybody who
    is marked "נתמך חגים")."""
    crit = {}
    given = event.get("criteria") or {}
    for field, _label in selection.FILTER_FIELDS:
        b = given.get(field) or {}
        lo, hi = b.get("min"), b.get("max")
        if lo is not None or hi is not None:
            crit[field] = {"min": lo, "max": hi}
    crit[selection.HOLIDAY_KEY] = str(event.get("holiday") or "").strip() or selection.HOLIDAY_ANY
    return crit


def _num_text(x) -> str:
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,}"


def _why_outside(row: dict, crit: dict) -> tuple:
    """For a card that IS marked for the holiday but did not pass the event's filter:
    (labels of the filtered fields that have no value on the card, the thresholds it is
    outside of — in words). Read with the engine's own reader (selection.filter_value), so
    the words always agree with the decision; the card's own numbers are never quoted."""
    missing, failed = [], []
    for field, label in selection.FILTER_FIELDS:
        b = crit.get(field) or {}
        lo, hi = b.get("min"), b.get("max")
        if lo is None and hi is None:
            continue
        val = selection.filter_value(row, field)
        if val is None:
            missing.append(label)
        elif lo is not None and val < lo:
            failed.append(f"{label} מתחת ל-{_num_text(lo)}")
        elif hi is not None and val > hi:
            failed.append(f"{label} מעל {_num_text(hi)}")
    return missing, failed


def _event_kind(row: dict) -> str:
    return participation(row) or KIND_OTHER


_EV_OUT_ORDER = {OUT_REMOVED: -1, OUT_EV_MISSING: 0, OUT_EV_CUT: 1, OUT_NO_PORTIONS: 1,
                 OUT_EV_FILTER: 2, OUT_EV_OTHER: 3}


def plan_event(event: dict, people: list, ledger: Ledger, *, weights: dict) -> dict:
    """The list of ONE holiday event. `event`: {guid, date, holiday ('*' = everybody marked
    "נתמך חגים", or a holiday's name), portions, reserve, criteria {field: {min, max}},
    manual {guid: 'add' | 'reserve' | 'remove'}}. `people`: active cards, ordered by name.

    Who is on it is decided by the engine, in the order the desktop program builds a holiday
    list (database.get_filtered_list, without the community balance):
      1. the holiday mark is a HARD gate (selection.holiday_filter) — also for the reserve:
         nobody who is not marked gets onto either list by himself;
      2. the turn gates are skipped — an extra round takes regulars whatever their turn
         and one-timers whatever their pause (selection.due_filter, ignore=True);
      3. every threshold that was set must hold, and a card with no value in a filtered
         field does not pass (selection.filter_by_criteria; 0 in income / per-soul = unknown);
      4. short of portions -> whoever waited longest (selection.rank_by_wait), then the
         reserve; the rest are off this list.
    What the manager set by hand comes first, as in a week: 'add' takes a portion and counts
    as received, 'reserve' / 'remove' do not. Nothing is recorded here."""
    day = event["date"]
    portions = max(0, int(event.get("portions") or 0))
    reserve = max(0, int(event.get("reserve") or 0))
    crit = event_criteria(event)
    code = crit[selection.HOLIDAY_KEY]
    filtered = any(f in crit for f, _label in selection.FILTER_FIELDS)
    manual = event.get("manual") or {}
    mark = "נתמך חגים" if code == selection.HOLIDAY_ANY else f"נתמך חגים ({code})"
    group_words = selection.holiday_label(crit)                 # "נתמכי חגים" / "נתמכי פסח"
    none_left = "מי שעובר את הסינון" if filtered else group_words

    by_hand = {MANUAL_ADD: [], MANUAL_RESERVE: [], MANUAL_REMOVE: []}
    free = []
    for p in people:
        row = event_row(p, day, ledger)
        action = manual.get(p.get("guid"))
        (by_hand[action] if action in by_hand else free).append(row)
    marked_total = sum(1 for r in free + by_hand[MANUAL_ADD] + by_hand[MANUAL_RESERVE] + by_hand[MANUAL_REMOVE]
                       if selection.holiday_matches(r, crit))

    marked = selection.holiday_filter(free, crit)
    marked = selection.due_filter(marked, selection.upcoming_wednesday(day), ignore=True)
    eligible = selection.filter_by_criteria(marked, crit)
    ranked = selection.rank_by_wait(eligible, weights)
    n = len(ranked)
    many = f"{n} שעוברים את הסינון" if filtered else f"{n} {group_words}"

    main, reserve_list, out, warnings = [], [], [], []
    for r in by_hand[MANUAL_REMOVE]:
        out.append(_entry(r, _event_kind(r), ROLE_OUT,
                          "הוסר ביד מהחלוקה הזו · לא נחשב כמי שקיבל",
                          group=OUT_REMOVED, manual=MANUAL_REMOVE, sort=(r.get("full_name") or "",)))

    # everybody else who is not in the line, by reason
    in_line, gate = {id(r) for r in eligible}, {id(r) for r in marked}
    missing_n = unmarked = 0
    for r in free:
        if id(r) in in_line:
            continue
        name = r.get("full_name") or ""
        if id(r) not in gate:
            if holidays.is_supported(r):
                out.append(_entry(r, _event_kind(r), ROLE_OUT,
                                  f"מסומן נתמך חגים רק ל: {holidays.display(r)} · לא לחג הזה",
                                  group=OUT_EV_OTHER, sort=(name,)))
            else:
                unmarked += 1          # not marked at all: counted, not listed
            continue
        missing, failed = _why_outside(r, crit)
        if failed:
            out.append(_entry(r, _event_kind(r), ROLE_OUT,
                              f"{mark}, אבל לא עובר את הסינון: {' · '.join(failed)}",
                              group=OUT_EV_FILTER, sort=(name,)))
        else:
            missing_n += 1
            out.append(_entry(r, _event_kind(r), ROLE_OUT,
                              f"{mark}, אבל חסר בכרטיס: {', '.join(missing) or 'נתון'} · "
                              "בלי זה אי אפשר לדעת אם הוא עובר את הסינון",
                              group=OUT_EV_MISSING, sort=(name,)))
    if missing_n:
        warnings.append(f"{missing_n} {group_words} לא נכנסו כי חסר להם נתון בכרטיס")

    def result(cut):
        out.sort(key=lambda e: (_EV_OUT_ORDER.get(e.get("group"), 9), e.pop("sort", ("",))))
        return {
            "guid": event.get("guid"), "date": day, "holiday": code,
            "portions": portions, "reserve": reserve,
            "criteria": {f: crit[f] for f, _label in selection.FILTER_FIELDS if f in crit},
            "main": main, "reserve_list": reserve_list, "out": out, "warnings": warnings,
            "marked": marked_total, "eligible": n, "missing": missing_n, "unmarked": unmarked,
            "cut": cut, "empty_portions": max(0, portions - len(main)),
        }

    passes = f"{mark} · עובר את הסינון" if filtered else mark
    if portions <= 0:
        # as in a week (rule 8): no portions -> an empty list, and nobody is recorded
        warnings.insert(0, "0 מנות: הרשימה של החלוקה הזו ריקה")
        for r in by_hand[MANUAL_ADD] + by_hand[MANUAL_RESERVE]:
            out.append(_entry(r, _event_kind(r), ROLE_OUT, "סומן ביד לחלוקה הזו, אבל אין בה מנות",
                              group=OUT_NO_PORTIONS, manual=manual[r["guid"]],
                              sort=(0, r.get("full_name") or "")))
        for i, r in enumerate(ranked):
            out.append(_entry(r, _event_kind(r), ROLE_OUT, f"{passes} · אין מנות בחלוקה הזו",
                              group=OUT_NO_PORTIONS, sort=(1, i)))
        return result(False)

    for r in by_hand[MANUAL_ADD]:
        main.append(_entry(r, _event_kind(r), ROLE_MAIN,
                           "נוסף ביד לחלוקה הזו · נחשב כמי שקיבל", manual=MANUAL_ADD))
    for r in by_hand[MANUAL_RESERVE]:
        reserve_list.append(_entry(r, _event_kind(r), ROLE_RESERVE,
                                   "הועבר ביד לרזרבה · נכנס אם מישהו לא מגיע, ולא נחשב כמי שקיבל",
                                   manual=MANUAL_RESERVE))
    slots = max(0, portions - len(by_hand[MANUAL_ADD]))
    selection.assign_roles(ranked, slots, max(0, reserve - len(by_hand[MANUAL_RESERVE])))
    cut = n > slots
    if cut:
        warnings.insert(0, f"{many} ורק {portions} מנות: נכנסו מי שמחכים הכי הרבה זמן")
    for i, r in enumerate(ranked):
        if r["_role"] == ROLE_MAIN:
            why = f"{passes} · {_last_text(r)}"
            if cut:
                why += f" · נכנס כי הוא מחכה {r.get('days_since') or 0} ימים, יותר מאחרים"
            main.append(_entry(r, _event_kind(r), ROLE_MAIN, why))
        elif r["_role"] == ROLE_RESERVE:
            reserve_list.append(_entry(
                r, _event_kind(r), ROLE_RESERVE,
                f"{mark} · יש {many} ורק {portions} מנות · רזרבה: נכנס אם מישהו לא מגיע"))
        else:
            out.append(_entry(
                r, _event_kind(r), ROLE_OUT,
                f"{mark} · יש {many} ורק {portions} מנות · לא נשאר מקום גם ברזרבה",
                group=OUT_EV_CUT, sort=(i,)))
    empty = portions - len(main)
    if empty > 0:
        warnings.append(f"{empty} מנות נשארו בלי מקבל: אין עוד {none_left}")
    elif empty < 0:
        warnings.append(f"ברשימה {len(main)} מקבלים ויש רק {portions} מנות: "
                        f"{-empty} יותר מדי, בגלל הוספות ביד")
    return result(cut)


# ── many weeks ────────────────────────────────────────────────────────────────
def active_people(recipients) -> list:
    """Active cards in the order the lists are built from: by name (then by id, so two
    cards with the same name keep a stable order)."""
    return sorted((r for r in recipients if is_active(r)),
                  key=lambda r: (r.get("full_name") or "", r.get("id") or 0))


def _event_order(event: dict) -> tuple:
    """Events are laid out by date; two on one day keep the order they were created in."""
    return (event["date"], str(event.get("created_at") or ""), str(event.get("guid") or ""))


def plan_timeline(recipients, received, *, start: date, weeks: int, horizon: date,
                  weights: dict, cooldown_weeks: int, portions: int = 52, reserve: int = 0,
                  per_week: dict = None, manual: dict = None, events: list = None) -> dict:
    """Lay out `weeks` consecutive Wednesdays from `start`, and the holiday events that
    fall among them, ALL IN DATE ORDER — each round sees what the rounds before it gave.

    recipients — every card (dicts); only active ones take part.
    received   — history rows (dicts: recipient_guid, dist_date, received, holiday).
    horizon    — the upcoming Wednesday as of today (history dated after it is ignored).
    per_week   — optional {Wednesday: {"portions": n, "reserve": n}} for single weeks.
    manual     — optional {Wednesday: {guid: 'add' | 'reserve' | 'remove'}} (see plan_week).
    events     — optional holiday events that have not happened yet (see plan_event).

    The order of the rounds: an event dated before a Wednesday is laid out before that
    week; an event ON a Wednesday is the extra round of that day and comes after the
    regular list (so the regular list is exactly what it would be without the event).
    After a week its MAIN list counts as received in a regular round; after an event its
    MAIN list counts as received in an extra round. The reserve never does.

    Returns {"weeks": [...], "events": [the events that were laid out, in order],
    "later": [events dated on or after the first Wednesday that was NOT laid out — their
    lists depend on weeks that were not asked for, so they are not computed]}.
    The inputs are not modified; the same inputs always give the same lists."""
    if start.weekday() != 2:
        raise ValueError("start must be a Wednesday")
    people = active_people(recipients)
    ledger = Ledger(horizon).load(received)
    pending = sorted(events or [], key=_event_order)
    out_weeks, out_events = [], []

    def lay_out_events(until: date, including: bool):
        while pending and (pending[0]["date"] < until or (including and pending[0]["date"] == until)):
            event = pending.pop(0)
            laid = plan_event(event, people, ledger, weights=weights)
            out_events.append(laid)
            for e in laid["main"]:
                ledger.add_extra(e["guid"], event["date"])

    weeks = max(0, int(weeks))
    for i in range(weeks):
        wed = start + timedelta(days=7 * i)
        lay_out_events(wed, False)
        over = (per_week or {}).get(wed) or {}
        week = plan_week(wed, people, ledger,
                         portions=over.get("portions", portions),
                         reserve=over.get("reserve", reserve),
                         weights=weights, cooldown_weeks=cooldown_weeks,
                         manual=(manual or {}).get(wed))
        out_weeks.append(week)
        for e in week["main"]:
            ledger.add_regular(e["guid"], wed)
        lay_out_events(wed, True)
    # ...and the events up to the first Wednesday that was NOT laid out: every week they
    # depend on is already here (with no week asked for: the events before `start`)
    lay_out_events(start + timedelta(days=7 * weeks), False)
    return {"weeks": out_weeks, "events": out_events, "later": pending}


def plan_weeks(recipients, received, *, start: date, weeks: int, horizon: date,
               weights: dict, cooldown_weeks: int, portions: int = 52, reserve: int = 0,
               per_week: dict = None, manual: dict = None, events: list = None) -> list:
    """The weeks of plan_timeline (the holiday events among them are laid out too — the
    weeks after an event depend on it — but only the weeks are returned)."""
    return plan_timeline(recipients, received, start=start, weeks=weeks, horizon=horizon,
                         weights=weights, cooldown_weeks=cooldown_weeks, portions=portions,
                         reserve=reserve, per_week=per_week, manual=manual, events=events)["weeks"]


def weeks_through(start: date, day: date) -> int:
    """How many Wednesdays from `start` have to be laid out before an event on `day` can
    be: every Wednesday up to and including that day (0 when the day is before `start`)."""
    return 0 if day < start else (day - start).days // 7 + 1
