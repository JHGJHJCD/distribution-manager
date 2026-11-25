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
"""
import re
from bisect import bisect_left
from datetime import date, timedelta

from .engine import scoring, selection

_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

ACTIVE = "פעיל"
ONE_TIME = "חד-פעמי"
ROLE_MAIN, ROLE_RESERVE, ROLE_OUT = selection.ROLE_MAIN, selection.ROLE_RESERVE, selection.ROLE_OUT

KIND_REGULAR, KIND_ONE_TIME = "regular", "onetime"
# Why somebody is not on a week's list — the third column of the screen, by reason.
OUT_REG_WAIT = "reg_wait"      # a regular whose turn has not come (rule 6) / served this week (rule 9)
OUT_REG_CUT = "reg_cut"        # a regular whose turn came but the portions ran out (rule 8)
OUT_ONE_PAUSE = "one_pause"    # a one-timer inside the pause after receiving (rule 7)
OUT_ONE_QUEUE = "one_queue"    # a one-timer waiting in the queue, portions and reserve are full
OUT_NO_PORTIONS = "no_portions"
OUT_REMOVED = "removed"        # taken off this week's list by hand
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


def week_row(rec: dict, wed: date, ledger: Ledger) -> dict:
    """A copy of the card with the fields the engine reads, as they stand for the week of
    `wed`: last_distribution (any round), next_distribution (from the last REGULAR round),
    round_served (rule 9) and days_since. The card itself is never modified."""
    row = dict(rec)
    guid = rec.get("guid")
    base = to_date(rec.get("last_dist_base"))
    if base is not None and base > ledger.horizon:
        base = None
    last_any = _later(ledger.last_any(guid), base)
    last_reg = _later(ledger.last_regular(guid), base)
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


# ── many weeks ────────────────────────────────────────────────────────────────
def active_people(recipients) -> list:
    """Active cards in the order the lists are built from: by name (then by id, so two
    cards with the same name keep a stable order)."""
    return sorted((r for r in recipients if is_active(r)),
                  key=lambda r: (r.get("full_name") or "", r.get("id") or 0))


def plan_weeks(recipients, received, *, start: date, weeks: int, horizon: date,
               weights: dict, cooldown_weeks: int, portions: int = 52, reserve: int = 0,
               per_week: dict = None, manual: dict = None) -> list:
    """Lay out `weeks` consecutive Wednesdays from `start`.

    recipients — every card (dicts); only active ones take part.
    received   — history rows (dicts: recipient_guid, dist_date, received, holiday).
    horizon    — the upcoming Wednesday as of today (history dated after it is ignored).
    per_week   — optional {Wednesday: {"portions": n, "reserve": n}} for single weeks.
    manual     — optional {Wednesday: {guid: 'add' | 'reserve' | 'remove'}} (see plan_week).
    After each week its MAIN list counts as received; the reserve never does.
    The inputs are not modified; the same inputs always give the same lists."""
    if start.weekday() != 2:
        raise ValueError("start must be a Wednesday")
    people = active_people(recipients)
    ledger = Ledger(horizon).load(received)
    out = []
    for i in range(max(0, int(weeks))):
        wed = start + timedelta(days=7 * i)
        over = (per_week or {}).get(wed) or {}
        week = plan_week(wed, people, ledger,
                         portions=over.get("portions", portions),
                         reserve=over.get("reserve", reserve),
                         weights=weights, cooldown_weeks=cooldown_weeks,
                         manual=(manual or {}).get(wed))
        out.append(week)
        for e in week["main"]:
            ledger.add_regular(e["guid"], wed)
    return out
