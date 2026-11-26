# -*- coding: utf-8 -*-
"""Do the website's tests really bite?  (project rule: a test must be seen failing.)

Breaks the site in one way at a time and runs the test file that should notice against
the broken version; every break must make that file FAIL. Run by hand after touching the
tests:
    <python 3.12> web/tests/mutation_check.py
"""
import contextlib
import io
import os
import runpy
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _util  # noqa: E402,F401  (puts the repository root on sys.path)

from web import (app as webapp, card_service, cards, config, event_service, history_service, planner,  # noqa: E402
                 service, settings_service, store)
from web.engine import selection  # noqa: E402

PLANNER, STORE, API, CARDS = "test_planner.py", "test_store.py", "test_api.py", "test_cards.py"
HISTORY, SETTINGS = "test_history.py", "test_settings.py"


def run(target: str):
    """Run one test file inside this process (so it sees the broken module).
    Returns (exit code, what noticed: the first failing check, or the crash)."""
    buf = io.StringIO()
    keep_now, keep_env = config.now, dict(os.environ)      # the test files set these for themselves
    code, crash = 0, ""
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            runpy.run_path(os.path.join(HERE, target), run_name="__main__")
    except SystemExit as e:
        code = int(e.code or 0)
    except Exception as e:            # a broken site may crash the test script: also a catch
        code, crash = 1, f"the test stopped: {type(e).__name__}: {e}"
    finally:
        config.now = keep_now
        os.environ.clear()
        os.environ.update(keep_env)
    failed = [ln[4:].strip() for ln in buf.getvalue().splitlines() if ln.startswith("FAIL")]
    return code, (failed[0][:110] + (f"  (+{len(failed) - 1} more)" if len(failed) > 1 else "")) if failed else crash


results = []


def mutate(target, name, obj, attr, broken):
    """Replace obj.attr with `broken`, run `target`, put the original back."""
    original = getattr(obj, attr)
    setattr(obj, attr, broken)
    try:
        code, noticed = run(target)
    finally:
        setattr(obj, attr, original)
    caught = code != 0
    print(f"  {'OK  caught' if caught else 'MISSED    '}  {target:<16} {name}")
    if caught:
        print(f"                {'':<16}   <- {noticed}")
    results.append(caught)


for target in (PLANNER, STORE, API, CARDS, HISTORY, SETTINGS):
    code, noticed = run(target)
    print(f"  {'OK' if code == 0 else 'FAIL'}  {target:<16} passes on the unbroken site (exit {code}) {noticed}")
    results.append(code == 0)
BASELINES = len(results)

# ── the planner: weeks, turns, history ────────────────────────────────────────
mutate(PLANNER, "a laid-out week is not recorded (nobody's turn advances)",
       planner.Ledger, "add_regular", lambda self, g, w: None)

mutate(PLANNER, "holiday / bonus rounds move the regular turn",
       planner, "is_extra_round", lambda d, h: False)

_init = planner.Ledger.__init__
mutate(PLANNER, "future (typo) dates are counted",
       planner.Ledger, "__init__", lambda self, horizon: _init(self, date.max))

mutate(PLANNER, "rule 9 is off (served this week, listed again)",
       planner.Ledger, "regular_between", lambda self, g, lo, hi: False)

_plan_week = planner.plan_week


def _reserve_receives(*a, **k):
    w = _plan_week(*a, **k)
    w["main"] = w["main"] + w["reserve_list"]
    return w


mutate(PLANNER, "the reserve is recorded as having received", planner, "plan_week", _reserve_receives)

mutate(PLANNER, "waiting days are ignored (who waited longest is lost)",
       planner, "recency_days", lambda rec, today: 0)

# ── the planner: what the manager sets by hand ────────────────────────────────
_plan_weeks = planner.plan_weeks


def _hand_ignored(*a, **k):
    k["manual"] = None
    return _plan_weeks(*a, **k)


mutate(PLANNER, "what was set by hand is ignored when the weeks are computed", planner, "plan_weeks", _hand_ignored)


def _hand_every_week(wed, people, ledger, **k):
    k["manual"] = _SPILL
    return _plan_week(wed, people, ledger, **k)


def _hand_spills(*a, **k):
    global _SPILL
    _SPILL = {}
    for per_week in (k.get("manual") or {}).values():
        _SPILL.update(per_week)
    return _plan_weeks(*a, **k)


_SPILL = {}
planner.plan_week = _hand_every_week
try:
    mutate(PLANNER, "a change set for one week applies to every week", planner, "plan_weeks", _hand_spills)
finally:
    planner.plan_week = _plan_week


def _removed_receives(wed, people, ledger, **k):
    w = _plan_week(wed, people, ledger, **k)
    for e in w["out"]:
        if e.get("manual") == planner.MANUAL_REMOVE:
            ledger.add_regular(e["guid"], wed)
    return w


mutate(PLANNER, "taken off a week by hand, but recorded as having received", planner, "plan_week", _removed_receives)


def _hand_reserve_receives(wed, people, ledger, **k):
    w = _plan_week(wed, people, ledger, **k)
    for e in w["reserve_list"]:
        if e.get("manual") == planner.MANUAL_RESERVE:
            ledger.add_regular(e["guid"], wed)
    return w


mutate(PLANNER, "moved to the reserve by hand, but recorded as having received", planner, "plan_week", _hand_reserve_receives)

_add_regular = planner.Ledger.add_regular
_NOT_COUNTED = set()


def _note_added(wed, people, ledger, **k):
    w = _plan_week(wed, people, ledger, **k)
    _NOT_COUNTED.update((e["guid"], wed) for e in w["main"] if e.get("manual") == planner.MANUAL_ADD)
    return w


def _skip_added(self, guid, wed):
    if (guid, wed) not in _NOT_COUNTED:
        _add_regular(self, guid, wed)


planner.plan_week = _note_added
try:
    mutate(PLANNER, "added by hand, but not counted as having received (his turn does not move)",
           planner.Ledger, "add_regular", _skip_added)
finally:
    planner.plan_week = _plan_week

# ── the store and the service: saving, closing, the print note ────────────────
mutate(STORE, "a change by hand is not saved", store, "set_manual", lambda conn, wed, guid, action, now: None)

_set_manual = store.set_manual
mutate(STORE, "'clear' does not forget the change",
       store, "set_manual", lambda conn, wed, guid, action, now: action and _set_manual(conn, wed, guid, action, now))

mutate(STORE, "the numbers set for a week are not used", store, "load_numbers", lambda conn: {})

_roll = service._roll


def _closes_without_hand(conn, now, db_path=None):
    keep = store.load_manual
    store.load_manual = lambda c: {}
    try:
        return _roll(conn, now, db_path)
    finally:
        store.load_manual = keep


mutate(STORE, "a week that closes by itself forgets what was set by hand for it", service, "_roll", _closes_without_hand)

_print_note = service._print_note


def _never_changed(w, ctx, names=None):
    note = _print_note(w, ctx, names)
    if note:
        note.update(changed=False, added=0, removed=0, **({"added_names": [], "removed_names": []} if names is not None else {}))
    return note


mutate(STORE, "a list that changed after it was printed says nothing", service, "_print_note", _never_changed)

_set_print = store.set_print
mutate(STORE, "printing keeps the first paper for ever (a second printing does not start afresh)",
       store, "set_print", lambda conn, wed, how, main, reserve, now:
       None if conn.execute("SELECT 1 FROM week_prints WHERE week_wed=?", (wed.isoformat(),)).fetchone()
       else _set_print(conn, wed, how, main, reserve, now))

_open_index = service._open_index


def _past_is_open(conn, now, wed):
    try:
        return _open_index(conn, now, wed)
    except LookupError:
        return 0


mutate(STORE, "a week that has passed can still be changed", service, "_open_index", _past_is_open)

_service_set_manual = service.set_manual


def _paused_is_welcome(conn, now, wed, guid, action, db_path=None):
    try:
        return _service_set_manual(conn, now, wed, guid, action, db_path)
    except service.Refused as e:
        if "מושהה" not in str(e):
            raise
        with store.tx(conn):
            store.set_manual(conn, wed, guid, action, now)


mutate(STORE, "a paused card can be put on a list by hand", service, "set_manual", _paused_is_welcome)

service.sorted = sorted                     # print_weeks finds this name before the built-in one
try:
    mutate(STORE, "the paper list is not ordered by name", service, "sorted", lambda entries, key=None: list(entries))
finally:
    del service.sorted

# ── the routes ────────────────────────────────────────────────────────────────
mutate(API, "a change is accepted without the site's own header", webapp, "_from_this_site", lambda request: True)

mutate(API, "a name that starts with '=' reaches Excel as a formula", service, "_keep_as_text", lambda cell, value: None)

_public = service._public
mutate(API, "the phones go out to the screen too",
       service, "_public", lambda entries: [dict(e, phones="0501234567") for e in _public(entries)])

_mark_printed = service.mark_printed
mutate(API, "printing is remembered for the first week of the range only",
       service, "mark_printed", lambda conn, now, start, weeks, how, db_path=None:
       _mark_printed(conn, now, start, 1, how, db_path) and weeks)

# ── stage 3: the recipients ───────────────────────────────────────────────────
mutate(CARDS, "the name is written given-name first", cards, "join_name",
       lambda first, last: f"{first} {last}".strip())

mutate(CARDS, "any word is accepted as a status", cards, "normalize_status", lambda val: "פעיל")

_row = card_service._row
mutate(CARDS, "the list carries the phones", card_service, "_row",
       lambda r, last: dict(_row(r, last), phone=r.get("phone1") or ""))

mutate(CARDS, "the search does not look at phones", cards, "phone_key", lambda p: "")

mutate(CARDS, "a new card with an existing name is added without asking", cards, "look_alikes",
       lambda recipients, full_name, numbers, exclude="": [])

_clean = cards.clean


def _kind_always_rewritten(data, existing=None):
    out = _clean(data, existing)
    if existing is not None and data.get("type") in cards._TYPE:
        _l, out["frequency"], out["priority"] = cards._TYPE[data["type"]]
    return out


mutate(CARDS, "saving a card rewrites its kind even when it was not changed", cards, "clean", _kind_always_rewritten)

mutate(CARDS, "a card is saved over a change that was made elsewhere meanwhile", card_service, "_unseen_version",
       lambda seen, card: False)


def _delete_anyway(conn, guid, now):
    conn.execute("DELETE FROM recipients WHERE guid=?", (guid,))


mutate(CARDS, "a card with history can be deleted", store, "delete_recipient", _delete_anyway)

mutate(CARDS, "a deleted card is not kept (it cannot be brought back)", store, "_remember_deleted",
       lambda conn, card, reason, now, merged_into="": None)

_groups = cards.duplicate_groups
mutate(CARDS, "'different people' is forgotten: the suggestion comes back", cards, "duplicate_groups",
       lambda recipients, different=(): _groups(recipients, ()))

_pick = cards.pick_keep
mutate(CARDS, "in a merge the card with LESS history stays", cards, "pick_keep",
       lambda a, b, n: tuple(reversed(_pick(a, b, n))))

_fill = cards.merge_fill
mutate(CARDS, "a merge drops the other card's phones and notes", cards, "merge_fill",
       lambda keep, drop, columns: {k: v for k, v in _fill(keep, drop, columns).items()
                                    if k not in ("phone1", "phone2", "phone3", "notes")})

mutate(CARDS, "a merge overwrites what the kept card already had", cards, "_blank", lambda v: True)

_merge = store.merge_recipients


def _history_left_behind(conn, keep_guid, drop_guid, fields, now):
    conn.execute("UPDATE history SET recipient_guid='' WHERE recipient_guid=?", (drop_guid,))
    return _merge(conn, keep_guid, drop_guid, fields, now)


mutate(CARDS, "a merge leaves the other card's history without a card", store, "merge_recipients", _history_left_behind)

_set_status = card_service.set_status
mutate(CARDS, "pausing a card does nothing", card_service, "set_status",
       lambda conn, now, guid, status: {"ok": True, "status": status})

mutate(CARDS, "a card is changed without the site's own header", webapp, "_from_this_site", lambda request: True)

# ── stage 4: holiday events — the planner ─────────────────────────────────────
mutate(PLANNER, "the holiday mark is no gate: everybody active is on a holiday list",
       selection, "holiday_filter", lambda rows, criteria: list(rows))

mutate(PLANNER, "a card with no value in a filtered field passes the event's filter",
       selection, "filter_value", lambda rec, field: selection.to_number(rec.get(field)) or 0)

mutate(PLANNER, "a holiday portion is forgotten: a later holiday list does not see it",
       planner.Ledger, "add_extra", lambda self, guid, day: None)

_week_row = planner.week_row


def _week_sees_extras(rec, wed, ledger):
    """Before the decision of 26/11/2026: a week counts a holiday / bonus portion as 'received last'."""
    row = _week_row(rec, wed, ledger)
    last_any = planner._last_dates(rec, ledger)[0]
    row["last_distribution"] = last_any.isoformat() if last_any else ""
    row["days_since"] = planner.recency_days(row, wed)
    return row


mutate(PLANNER, "the regular lists count a holiday portion (a one-timer is paused after it)", planner, "week_row", _week_sees_extras)

mutate(PLANNER, "a holiday round counts as a regular round (it moves a regular's turn)",
       planner.Ledger, "add_extra", planner.Ledger.add_regular)

_plan_event = planner.plan_event


def _reserve_topped_up(event, people, ledger, *, weights):
    """What the desktop SCREEN does (found 26/11/2026): fill a holiday reserve from the one-timers' queue."""
    e = _plan_event(event, people, ledger, weights=weights)
    listed = {x["guid"] for x in e["main"] + e["reserve_list"] + e["out"]}
    queue = [p for p in people if p["guid"] not in listed and selection.is_one_time_candidate(p)]
    for p in queue[:max(0, 5 - len(e["reserve_list"]))]:
        e["reserve_list"].append({"guid": p["guid"], "name": p["full_name"], "kind": "onetime", "freq": "חד-פעמי",
                                  "priority": p.get("priority"), "role": "reserve", "why": "רזרבה", "last": "",
                                  "days_since": 0, "score": None})
    return e


mutate(PLANNER, "the reserve of a holiday event is filled from the one-timers' queue (families that are not marked)",
       planner, "plan_event", _reserve_topped_up)


def _event_hand_ignored(event, people, ledger, *, weights):
    return _plan_event(dict(event, manual={}), people, ledger, weights=weights)


mutate(PLANNER, "what was set by hand for an event is ignored", planner, "plan_event", _event_hand_ignored)

_plan_timeline = planner.plan_timeline


def _event_before_its_wednesday(recipients, received, **k):
    """An event ON a Wednesday is laid out before that day's regular list."""
    moved = {}
    events = []
    for e in k.get("events") or []:
        if e["date"].weekday() == 2:
            moved[e.get("guid")] = e["date"]
            e = dict(e, date=e["date"] - timedelta(days=1))
        events.append(e)
    out = _plan_timeline(recipients, received, **dict(k, events=events))
    for e in out["events"]:
        if e["guid"] in moved:
            e["date"] = moved[e["guid"]]
    return out


mutate(PLANNER, "an event on a Wednesday is laid out before that day's regular list", planner, "plan_timeline", _event_before_its_wednesday)


def _event_numbers_quoted(event, people, ledger, *, weights):
    e = _plan_event(event, people, ledger, weights=weights)
    cards_ = {p["guid"]: p for p in people}
    for x in e["out"]:
        x["why"] += f" (הכנסה {cards_[x['guid']].get('income')})"
    return e


mutate(PLANNER, "the reason quotes the card's own income", planner, "plan_event", _event_numbers_quoted)

# ── stage 4: holiday events — the store, the closing, the routes ──────────────
mutate(STORE, "an event whose day has passed is never written to the history",
       store, "first_passed_event", lambda conn, before: None)

_first_passed = store.first_passed_event
mutate(STORE, "an event closes on its own day, before the morning after",
       store, "first_passed_event", lambda conn, before: _first_passed(conn, before + timedelta(days=1)))

_close_event = store.close_event
mutate(STORE, "a passed event is written as a REGULAR round (no holiday code: it moves the turn)",
       store, "close_event", lambda conn, plan, name, now: _close_event(conn, dict(plan, holiday=""), name, now))

mutate(STORE, "the reserve of a passed event is written as having received",
       store, "close_event", lambda conn, plan, name, now:
       _close_event(conn, dict(plan, main=plan["main"] + plan["reserve_list"]), name, now))

mutate(STORE, "of a week and an event of the same day, the event is written first",
       service, "_week_goes_first", lambda wed, event_day: wed < event_day)

_get_event = store.get_event


def _never_passed(conn, guid):
    e = _get_event(conn, guid)
    return dict(e, closed_at=None) if e else e


mutate(STORE, "an event that has passed can still be changed, set by hand and deleted", store, "get_event", _never_passed)

_event_save = event_service.save
mutate(STORE, "an event can be set up on a day that has passed",
       event_service, "save", lambda conn, now, data, db_path=None: _event_save(conn, now - timedelta(days=30), data, db_path))

_clean_criteria = event_service.clean_criteria
mutate(STORE, "any field can be used as an event's filter, and 'from' may be above 'up to'",
       event_service, "clean_criteria", lambda raw: {k: v for k, v in (raw or {}).items() if isinstance(v, dict)})

_event_set_manual = store.set_event_manual
mutate(STORE, "a change by hand for an event is not saved",
       store, "set_event_manual", lambda conn, guid, card, action, now: None)

mutate(STORE, "'clear' does not forget what was set by hand for an event",
       store, "set_event_manual", lambda conn, guid, card, action, now:
       action and _event_set_manual(conn, guid, card, action, now))

_since_print = service.since_print


def _event_never_changed(snap, now_main, names=None):
    note = _since_print(snap, now_main, names)
    if note:
        note.update(changed=False, added=0, removed=0, **({"added_names": [], "removed_names": []} if names is not None else {}))
    return note


mutate(STORE, "an event's list that changed after it was printed says nothing", service, "since_print", _event_never_changed)

_event_detail = event_service.detail


def _event_with_phones(conn, now, guid, db_path=None):
    d = _event_detail(conn, now, guid, db_path)
    d["phones"] = [r["phone1"] for r in conn.execute("SELECT phone1 FROM recipients")]
    return d


mutate(API, "the phones go out with the event's answer", event_service, "detail", _event_with_phones)

_paper_rows = service._paper_rows
mutate(API, "the paper sheet of an event carries the id numbers too",
       service, "_paper_rows", lambda entries, cards_:
       [dict(r, id_number=cards_.get(e["guid"], {}).get("id_number")) for r, e in zip(_paper_rows(entries, cards_), entries)])

_event_remove = event_service.remove
mutate(API, "deleting an event does nothing", event_service, "remove", lambda conn, now, guid, db_path=None: {"ok": True})

mutate(API, "bringing an event back does nothing", event_service, "restore",
       lambda conn, now, guid, db_path=None: {"ok": True, "guid": guid})


def _erase_event(conn, guid, now):
    for table in ("event_manual", "event_prints"):
        conn.execute(f"DELETE FROM {table} WHERE event_guid=?", (guid,))
    conn.execute("DELETE FROM events WHERE guid=?", (guid,))


mutate(STORE, "taking an event away erases it for good", store, "delete_event", _erase_event)


def _restore_on_any_day(conn, now, guid, db_path=None):
    with store.tx(conn):
        store.restore_event(conn, guid)
    return {"ok": True, "guid": guid}


mutate(STORE, "an event can be brought back after its day has passed", event_service, "restore", _restore_on_any_day)


def _passed_event_also_when_away(conn, before):
    r = conn.execute("SELECT guid FROM events WHERE closed_at IS NULL AND event_date < ? "
                     "ORDER BY event_date, created_at, guid LIMIT 1", (before.isoformat(),)).fetchone()
    return store.get_event(conn, r["guid"]) if r else None


mutate(STORE, "an event that was taken away is still written to the history when its day passes",
       store, "first_passed_event", _passed_event_also_when_away)

_deleted_events = store.deleted_events
mutate(STORE, "an event that can no longer be brought back is still offered", event_service, "overview",
       (lambda real: lambda conn, now, db_path=None: dict(real(conn, now, db_path), deleted=[
           {"guid": e["guid"], "date": e["date"].isoformat(), "day": "", "name": "", "portions": e["portions"]}
           for e in _deleted_events(conn)]))(event_service.overview))

# ── stage 4: the holiday mark on the card ─────────────────────────────────────
mutate(CARDS, "a holiday that does not exist can be written on a card",
       cards.holidays, "HOLIDAYS", list(cards.holidays.HOLIDAYS) + ["יום העצמאות"])

mutate(CARDS, "every card reads as marked for the holidays", cards, "holiday_text", lambda rec: "כל החגים")

_merge_fill = cards.merge_fill
mutate(CARDS, "in a merge the kept card's holiday mark is replaced by the other card's",
       cards, "merge_fill", lambda keep, drop, columns:
       dict(_merge_fill(keep, drop, columns), holiday_support=drop.get("holiday_support"), holidays=drop.get("holidays")))

_card_clean = cards.clean


def _holiday_free_text(data, existing=None):
    if isinstance(data.get("holidays"), str):
        data = dict(data, holidays=cards.holidays.parse_list(data["holidays"]))
    return _card_clean(data, existing)


mutate(CARDS, "free text is read as a list of holidays", cards, "clean", _holiday_free_text)

# ── stage 4: the history screen ───────────────────────────────────────────────
_hist_person = history_service._person
mutate(HISTORY, "a name in the history carries the card's phone along",
       history_service, "_person", lambda guid, written, cards_:
       dict(_hist_person(guid, written, cards_), phone=(cards_.get(guid) or {}).get("phone1")))

mutate(HISTORY, "a row whose card is gone is shown with no name at all",
       history_service, "_person", lambda guid, written, cards_: _hist_person(guid, "", cards_))


def _everybody_received(rows, cards_):
    return sorted((history_service._person(r["recipient_guid"], r["recipient_name"], cards_) for r in rows),
                  key=lambda p: p["name"]), []


mutate(HISTORY, "a row that says 'did not come' is listed among those who received", history_service, "_split", _everybody_received)

mutate(HISTORY, "a row that names a round that is not there falls between the two views",
       history_service, "_NO_ROUND", "(h.batch_guid IS NULL OR h.batch_guid='')")

mutate(HISTORY, "a date that is not a date floats to the top of 'the latest first'",
       history_service, "_latest_first", lambda column: f"{column} DESC")

_hist_overview = history_service.overview
mutate(HISTORY, "a page of rounds never says that there are more",
       history_service, "overview", lambda conn, now, offset=0, limit=history_service.PAGE, db_path=None:
       dict(_hist_overview(conn, now, offset, limit, db_path), more=False))

mutate(HISTORY, "a page size of nonsense returns no rounds at all",
       history_service, "_clamp", lambda value, low, high, default: value if isinstance(value, int) else 0)

_hist_round = history_service.round_detail


def _reserve_received(conn, now, batch, db_path=None):
    d = _hist_round(conn, now, batch, db_path)
    return dict(d, people=d["people"] + d["reserve"], reserve=[])


mutate(HISTORY, "who waited on the reserve of a closed week is listed as having received", history_service, "round_detail", _reserve_received)

mutate(HISTORY, "the kind of a round is lost: a holiday round reads as a regular one",
       history_service, "round_kind", lambda code: history_service.KIND_REGULAR)

_roll_forward = service.roll_forward
mutate(HISTORY, "opening the history does not first close the week that has passed",
       service, "roll_forward", lambda conn, now, db_path=None: [])

_hist_one = history_service.person


def _person_with_notes(conn, now, guid, db_path=None):
    d = _hist_one(conn, now, guid, db_path)
    card = store.get_recipient(conn, guid) or {}
    return dict(d, notes=card.get("notes"), phone=card.get("phone1"))


mutate(API, "one person's history answers with the card's note and phone", history_service, "person", _person_with_notes)

mutate(API, "the history's routes answer whatever is asked (a missing round is not refused)",
       history_service, "round_detail", lambda conn, now, batch, db_path=None: {"people": [], "absent_people": [], "reserve": []})

# ── stage 4: the settings screen ──────────────────────────────────────────────
_clean_weights = settings_service.clean_weights


def _any_sum(data):
    try:
        return _clean_weights(data)
    except service.Refused as e:
        if "להסתכם" not in str(e):
            raise
        return {k: float(data[k]) for k in settings_service.WEIGHT_KEYS}


mutate(SETTINGS, "weights that do not add up to 100 can be saved", settings_service, "clean_weights", _any_sum)

mutate(SETTINGS, "a weight may be negative, as long as the sum is 100", settings_service, "clean_weights",
       lambda data: {k: float(data[k]) for k in settings_service.WEIGHT_KEYS}
       if isinstance(data, dict) and set(data) == set(settings_service.WEIGHT_KEYS)
       and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v == v for v in data.values())
       and round(sum(data.values()), 1) == 100.0 else _clean_weights(data))

_clean_numbers = settings_service.clean_numbers
mutate(SETTINGS, "a number of portions above the ceiling can be saved", settings_service, "NUMBERS",
       tuple((n, k, label, 10 ** 9) for n, k, label, _top in settings_service.NUMBERS))

mutate(SETTINGS, "saving the numbers forgets the pause of the one-timers", settings_service, "NUMBERS",
       settings_service.NUMBERS[:2])

_save_weights = settings_service.save_weights
mutate(SETTINGS, "saving the weights saves nothing", settings_service, "save_weights",
       lambda conn, now, data, db_path=None: (_clean_weights(data), {"ok": True})[1])


def _preview_that_saves(conn, now, data, db_path=None):
    if data and data.get("weights") is not None:
        settings_service.save_weights(conn, now, data["weights"], db_path)
    if data and data.get("numbers") is not None:
        settings_service.save_numbers(conn, now, data["numbers"], db_path)
    return {"weeks": settings_service.PREVIEW_WEEKS, "changed": [], "same": True}


mutate(SETTINGS, "'what would change' saves what it was asked about", settings_service, "preview", _preview_that_saves)

_preview = settings_service.preview
mutate(SETTINGS, "'what would change' always answers that nothing changes", settings_service, "preview",
       lambda conn, now, data, db_path=None: dict(_preview(conn, now, data, db_path), changed=[], same=True))

mutate(SETTINGS, "'what would change' does not look as far as a holiday event that is ahead",
       settings_service.planner, "weeks_through", lambda start, day: 0)

mutate(SETTINGS, "the weights of the settings also reorder the one-timers' queue",
       settings_service.scoring, "ONE_TIME_QUEUE_WEIGHTS", {"money": 100.0, "souls": 0.0, "recency": 0.0,
                                                           "income": 0.0, "housing": 0.0, "medical": 0.0})

mutate(API, "the settings can be saved without checking them again on the server's side",
       settings_service, "clean_weights", lambda data: {k: float((data or {}).get(k) or 0) for k in settings_service.WEIGHT_KEYS})

breaks = len(results) - BASELINES
if all(results):
    print(f"\nRESULT: ALL {breaks} BREAKS WERE CAUGHT — the website's tests bite ✓")
    sys.exit(0)
print(f"\nRESULT: {results.count(False)} of {breaks} breaks were NOT caught — strengthen the tests")
sys.exit(1)
