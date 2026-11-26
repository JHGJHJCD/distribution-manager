# -*- coding: utf-8 -*-
"""Do the website's tests really bite?  (project rule: a test must be seen failing.)

Breaks the site in one way at a time and runs the test file that should notice against
the broken version; every break must make that file FAIL. Run by hand after touching the
tests:
    <python 3.12> web/tests/mutation_check.py [only]

`only` (optional) = a regular expression: only the breaks whose test file or description
match it are run, e.g.  mutation_check.py "test_backup|backs itself up".

A break counts as caught when the test file FAILS. Read what noticed it: "the test stopped"
with an error that has nothing to do with the break is a false catch (see the lesson in
web/implementation-notes.md) — the break must be noticed for its own reason.
"""
import contextlib
import io
import os
import re
import runpy
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _util  # noqa: E402,F401  (puts the repository root on sys.path)

from web import (app as webapp, auth, google_login, offsite, server_check, backup_service, card_service, cards, config, event_service, history_service,  # noqa: E402
                 planner, service, settings_service, store)
from web.engine import selection  # noqa: E402

PLANNER, STORE, API, CARDS = "test_planner.py", "test_store.py", "test_api.py", "test_cards.py"
HISTORY, SETTINGS, BACKUP = "test_history.py", "test_settings.py", "test_backup.py"
AUTH = "test_auth.py"             # the login of the server stage
SERVER = "test_server.py"         # the backup that leaves the server, and the readiness check
COMPARE = "test_compare.py"       # the test of the comparison tool (web/tests/local_check_real.py)


def run(target: str):
    """Run one test file inside this process (so it sees the broken module).
    Returns (exit code, what noticed: the first failing check, or the crash)."""
    buf = io.StringIO()
    keep_env = dict(os.environ)                            # the test files set these for themselves
    # ...and what a test file swaps inside the site for a few of its checks: when a broken
    # site stops the file in the middle, the swap must not leak into the next break
    keep = [(obj, attr, getattr(obj, attr)) for obj, attr in _SWAPPED_BY_TESTS]
    code, crash = 0, ""
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            runpy.run_path(os.path.join(HERE, target), run_name="__main__")
    except SystemExit as e:
        code = int(e.code or 0)
    except Exception as e:            # a broken site may crash the test script: also a catch
        code, crash = 1, f"the test stopped: {type(e).__name__}: {e}"
    finally:
        for obj, attr, value in keep:
            setattr(obj, attr, value)
        os.environ.clear()
        os.environ.update(keep_env)
    failed = [ln[4:].strip() for ln in buf.getvalue().splitlines() if ln.startswith("FAIL")]
    return code, (failed[0][:110] + (f"  (+{len(failed) - 1} more)" if len(failed) > 1 else "")) if failed else crash


_SWAPPED_BY_TESTS = [(config, "now"), (config, "backup_dir"), (store, "backup"), (store, "COPY_SECONDS"),
                     (offsite.shutil, "copyfile"), (google_login, "fetch_token")]
ONLY = re.compile(sys.argv[1]) if len(sys.argv) > 1 else None
results = []


def mutate(target, name, obj, attr, broken):
    """Replace obj.attr with `broken`, run `target`, put the original back."""
    if ONLY and not ONLY.search(f"{target} {name}"):
        return
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


for target in (PLANNER, STORE, API, CARDS, HISTORY, SETTINGS, BACKUP, COMPARE, AUTH, SERVER):
    if ONLY and not ONLY.search(target) and target != API:
        continue
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


def _reserve_topped_up(event, people, ledger, **kw):
    """What the desktop SCREEN does (found 26/11/2026): fill a holiday reserve from the one-timers' queue."""
    e = _plan_event(event, people, ledger, **kw)
    listed = {x["guid"] for x in e["main"] + e["reserve_list"] + e["out"]}
    queue = [p for p in people if p["guid"] not in listed and selection.is_one_time_candidate(p)]
    for p in queue[:max(0, 5 - len(e["reserve_list"]))]:
        e["reserve_list"].append({"guid": p["guid"], "name": p["full_name"], "kind": "onetime", "freq": "חד-פעמי",
                                  "priority": p.get("priority"), "role": "reserve", "why": "רזרבה", "last": "",
                                  "days_since": 0, "score": None})
    return e


mutate(PLANNER, "the reserve of a holiday event is filled from the one-timers' queue (families that are not marked)",
       planner, "plan_event", _reserve_topped_up)


def _event_hand_ignored(event, people, ledger, **kw):
    return _plan_event(dict(event, manual={}), people, ledger, **kw)


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


def _event_numbers_quoted(event, people, ledger, **kw):
    e = _plan_event(event, people, ledger, **kw)
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

# ── after stage 4: a week by need score ───────────────────────────────────────
_cut_by_score = planner._cut_by_score


def _score_week_by_wait(due, by_hand, weights, portions, reserve_auto):
    ranked = selection.rank_by_wait(due, weights)
    slots = max(0, portions - len(by_hand[planner.MANUAL_ADD]))
    selection.assign_roles(ranked, slots, reserve_auto)
    return ranked, len(ranked) > slots


mutate(PLANNER, "a week that is marked 'by score' is cut by who waited longest", planner, "_cut_by_score", _score_week_by_wait)

mutate(PLANNER, "every week is cut by score, marked or not", planner, "MODE_SCORED", None)

mutate(PLANNER, "by score, who is added by hand does not take a place from the lowest", planner, "_cut_by_score",
       lambda due, by_hand, weights, portions, reserve_auto:
       _cut_by_score(due, dict(by_hand, **{planner.MANUAL_ADD: []}), weights, portions, reserve_auto))

mutate(PLANNER, "by score, the regulars who were cut are not put on the reserve", planner, "_cut_by_score",
       lambda due, by_hand, weights, portions, reserve_auto: _cut_by_score(due, by_hand, weights, portions, 0))

_entry = planner._entry
mutate(PLANNER, "a reason quotes the money of the card", planner, "_entry",
       lambda row, kind, role, why, **extra: _entry(row, kind, role, f"{why} · {row.get('per_soul')} · {row.get('income')}", **extra))

mutate(STORE, "the mark 'by score' is not stored", store, "set_mode", lambda conn, wed, mode, now: None)


class _EveryWeek(dict):
    def get(self, key, default=None):
        return "scored"


mutate(STORE, "the mark 'by score' of one week applies to every week", store, "load_modes", lambda conn: _EveryWeek())

mutate(STORE, "a way of cutting a week that does not exist is accepted", planner, "WEEK_MODES", ("wait", "scored", "random"))

# ── after stage 4: a holiday list split between the communities ───────────────
_plan_event = planner.plan_event
mutate(PLANNER, "the split between the communities is ignored: the list is cut by who waited longest", planner, "plan_event",
       lambda event, people, ledger, **kw: _plan_event(dict(event, balance=False), people, ledger, **kw))

mutate(PLANNER, "the percentages fixed for communities are ignored", planner, "plan_event",
       lambda event, people, ledger, weights, pinned=None: _plan_event(event, people, ledger, weights=weights, pinned=None))

_criteria_gap = selection.criteria_gap
mutate(PLANNER, "a share is topped up with whoever is neediest, not with the nearest to the filter",
       selection, "criteria_gap", lambda rec, criteria: 0.0)

_communities = planner._communities
mutate(PLANNER, "the shares the screen shows are not the ones the list was built with", planner, "_communities",
       lambda marked, eligible, main_rows, slots, pinned: _communities(marked, eligible, main_rows, slots + 1, pinned))

_balance = selection.balance_by_community
mutate(PLANNER, "in a split list a share is filled with members who are not marked for the holidays", planner, "plan_event",
       (lambda real: lambda event, people, ledger, **kw:
        real(event, [dict(p, holiday_support=1, holidays="") for p in people], ledger, **kw))(_plan_event))

mutate(PLANNER, "a split list has no reserve", selection, "balance_by_community",
       lambda rows, criteria, weights, n_products, manual_pcts=None, reserve_count=0:
       _balance(rows, criteria, weights, n_products, manual_pcts, reserve_count=0))

_save_event = store.save_event
mutate(STORE, "the split of an event is not saved", store, "save_event",
       lambda conn, guid, day, holiday, portions, reserve, criteria, now, balance=False:
       _save_event(conn, guid, day, holiday, portions, reserve, criteria, now, False))

mutate(STORE, "the percentages fixed for communities are never read", store, "community_pcts", lambda settings: {})

_clean_communities = settings_service.clean_communities
mutate(SETTINGS, "the percentages of the communities may pass 100", settings_service, "clean_communities",
       lambda data, sizes: {k: float(v) for k, v in (data or {}).items() if isinstance(v, (int, float)) and v > 0}
       if isinstance(data, dict) and set(data) <= set(sizes)
       and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100 and round(v, 1) == round(v, 6)
               for v in data.values()) else _clean_communities(data, sizes))

mutate(SETTINGS, "a percentage is saved for a community nobody belongs to", settings_service, "clean_communities",
       lambda data, sizes: _clean_communities(data, dict(sizes, **{k: 1 for k in (data or {})})) if isinstance(data, dict)
       else _clean_communities(data, sizes))

_sizes = settings_service.community_sizes


def _sizes_with_paused(conn):
    sizes = {}
    for r in store.load_recipients(conn):
        key = selection.community_key(r)
        sizes[key] = sizes.get(key, 0) + 1
    none = sizes.pop(selection.NO_COMMUNITY, 0)
    return sizes, none


mutate(SETTINGS, "paused cards are counted in the size of a community", settings_service, "community_sizes", _sizes_with_paused)

_changed_context = settings_service._changed_context
mutate(SETTINGS, "'what would change' ignores the percentages that were typed", settings_service, "_changed_context",
       lambda conn, ctx, data: _changed_context(conn, ctx, dict(data, communities=None)))

_event_detail = event_service.detail
mutate(API, "the shares of the communities are not sent to the screen", event_service, "detail",
       lambda conn, now, guid, db_path=None: dict(_event_detail(conn, now, guid, db_path), communities=[]))

mutate(API, "who came in to fill a community's share is not marked for the screen", service, "_ENTRY_FIELDS",
       tuple(f for f in service._ENTRY_FIELDS if f != "fill"))

# ── stage 5: backup and restore ───────────────────────────────────────────────
import sqlite3  # noqa: E402

_bk_check, _bk_path, _bk_restore, _bk_all = (backup_service.check, backup_service._path, backup_service.restore,
                                             backup_service._all)


def _restore_with_no_way_back(conn, now, name, db_path):
    path = _bk_path(name)
    inside = _bk_check(path)
    src, dst = backup_service._open_read_only(path), sqlite3.connect(db_path, timeout=1)
    try:
        store.copy_database(src, dst)
    finally:
        dst.close()
        src.close()
    store._ensured.discard(db_path)
    store.ensure_schema(db_path)
    return {"ok": True, "restored": name, "safety": "", "backup": inside}


mutate(BACKUP, "a restore does not back up the state it is about to replace", backup_service, "restore", _restore_with_no_way_back)


def _damaged_is_fine(path):
    try:
        return _bk_check(path)
    except service.Refused as e:
        if "פגום" not in str(e):
            raise
        return {}


mutate(BACKUP, "a damaged file is not refused before a restore", backup_service, "check", _damaged_is_fine)


def _other_database_is_fine(path):
    try:
        return _bk_check(path)
    except service.Refused as e:
        if "אינו גיבוי" not in str(e) and "גרסה אחרת" not in str(e):
            raise
        return {"cards": 0, "active": 0, "history_rows": 0, "rounds": 0, "last_week": "", "events_ahead": 0}


mutate(BACKUP, "a database that is not this site's (or of a newer version) can be restored", backup_service, "check",
       _other_database_is_fine)

mutate(BACKUP, "a restore takes any path of the computer, not only a backup of the site's own folder", backup_service, "_path",
       lambda name: name if isinstance(name, str) and os.path.isfile(name) else _bk_path(name))

mutate(BACKUP, "a backup inside a sub-folder of the backup folder can be named", backup_service, "_path",
       lambda name: os.path.join(config.backup_dir(), name)
       if isinstance(name, str) and os.path.isfile(os.path.join(config.backup_dir(), name)) else _bk_path(name))

mutate(BACKUP, "the list of backups is oldest first", backup_service, "_all", lambda folder: _bk_all(folder)[::-1])


def _daily_every_time(conn, now, db_path):
    made = store.backup(db_path, config.backup_dir(), backup_service.DAILY, now)
    with store.tx(conn):
        store.set_meta(conn, backup_service.DAY_KEY, now.date().isoformat())
    return os.path.basename(made)


mutate(BACKUP, "the site backs itself up on every request, not once a day", backup_service, "daily", _daily_every_time)
mutate(API, "the site backs itself up on every request, not once a day (through the routes)", backup_service, "daily",
       _daily_every_time)
mutate(API, "the site never backs itself up", backup_service, "daily", lambda conn, now, db_path: "")


def _daily_that_can_fail(conn, now, db_path):
    today = now.date().isoformat()
    if store.get_meta(conn, backup_service.DAY_KEY) == today:
        return ""
    with store.tx(conn):
        made = store.backup(db_path, config.backup_dir(), backup_service.DAILY, now)
        store.set_meta(conn, backup_service.DAY_KEY, today)
    return os.path.basename(made)


mutate(BACKUP, "a daily backup that cannot be written stops the site", backup_service, "daily", _daily_that_can_fail)


def _daily_marked_first(conn, now, db_path):
    today = now.date().isoformat()
    if store.get_meta(conn, backup_service.DAY_KEY) == today:
        return ""
    with store.tx(conn):
        store.set_meta(conn, backup_service.DAY_KEY, today)
    try:
        return os.path.basename(store.backup(db_path, config.backup_dir(), backup_service.DAILY, now))
    except OSError:
        return ""


mutate(BACKUP, "a day whose backup failed is marked as backed up (and is never tried again)", backup_service, "daily",
       _daily_marked_first)

mutate(BACKUP, "a restored database is not brought up to the tables and columns the site needs", store, "ensure_schema",
       lambda path: None)

mutate(BACKUP, "'back up now' says it did and writes nothing", backup_service, "make",
       lambda conn, now, db_path: {"ok": True, "name": f"haluka-{now.strftime('%Y%m%d-%H%M%S')}-manual.db"})

_bk_inspect = backup_service.inspect


def _sides_swapped(conn, now, name, db_path=None):
    d = _bk_inspect(conn, now, name, db_path)
    return dict(d, backup=d["now"], now=d["backup"])


mutate(BACKUP, "the look at a backup shows the site's numbers as the backup's (and the other way)", backup_service, "inspect",
       _sides_swapped)

mutate(BACKUP, "the weeks that became history since a backup are never counted", backup_service, "_weeks_between",
       lambda earlier, later: 0)

_store_backup = store.backup


def _keep_only_the_latest(path, backup_dir, reason, now=None):
    made = _store_backup(path, backup_dir, reason, now)
    olds = sorted(f for f in os.listdir(backup_dir) if backup_service.NAME.match(f) and os.path.isfile(os.path.join(backup_dir, f)))
    for f in olds[:-6]:
        os.remove(os.path.join(backup_dir, f))
    return made


mutate(BACKUP, "old backups are thrown out when a new one is taken", store, "backup", _keep_only_the_latest)


def _restore_forgets_the_day(conn, now, name, db_path):
    done = _bk_restore(conn, now, name, db_path)
    with store.tx(conn):
        store.set_meta(conn, backup_service.DAY_KEY, "")
    return done


mutate(BACKUP, "after a restore the restored state is backed up again as if it were this morning's", backup_service, "restore",
       _restore_forgets_the_day)

mutate(BACKUP, "a reason for a backup has no words on the screen", backup_service, "REASONS",
       {k: v for k, v in backup_service.REASONS.items() if k != "before-merge-cards"})


def _look_with_a_person(conn, now, name, db_path=None):
    d = _bk_inspect(conn, now, name, db_path)
    row = conn.execute("SELECT full_name, phone1 FROM recipients LIMIT 1").fetchone()
    return dict(d, sample={"name": row[0], "phone": row[1]})


mutate(API, "the look at a backup answers with a person out of it", backup_service, "inspect", _look_with_a_person)

mutate(API, "a restore through the site restores nothing and says it did", backup_service, "restore",
       lambda conn, now, name, db_path: {"ok": True, "restored": name, "safety": os.path.basename(
           store.backup(db_path, config.backup_dir(), backup_service.BEFORE_RESTORE, now)), "backup": {}})

_copy_database = store.copy_database
mutate(BACKUP, "a copy waits much longer than it says for a database that is busy", store, "copy_database",
       lambda src, dst, seconds=None: _copy_database(src, dst, 12))


def _backup_leaves_a_stub(path, backup_dir, reason, now=None):
    try:
        return _store_backup(path, backup_dir, reason, now)
    except sqlite3.OperationalError:
        open(os.path.join(backup_dir, f"haluka-{now.strftime('%Y%m%d-%H%M%S')}-{reason}.db"), "wb").close()
        raise


mutate(BACKUP, "a backup that could not be finished leaves an empty file with a backup's name", store, "backup",
       _backup_leaves_a_stub)

# ── stage 5: the comparison tool (it is run by hand on real data, so its own test must bite) ──
import local_check_real as compare_tool  # noqa: E402

_render, _run_compare, _kind_of, _differences = (compare_tool.render, compare_tool.run, compare_tool.kind_of,
                                                 compare_tool.differences)
mutate(COMPARE, "the report says 'the same lists' whatever was found", compare_tool, "render",
       lambda result: _render(dict(result, identical=True, differ=0)))

mutate(COMPARE, "a difference names the person", compare_tool, "kind_of",
       lambda entry, card: (card or {}).get("full_name") or _kind_of(entry, card))


def _free_text_reasons(a, old_main, old_reserve, cards):
    rows = _differences(a, old_main, old_reserve, cards)
    why = {e["guid"]: e.get("why") or "" for key in ("main", "reserve_list", "out") for e in a[key]}
    for row, g in zip(rows, [g for g in why]):
        row["why"] = why[g]
    return rows


mutate(COMPARE, "a difference quotes the site's free-text reason (it can name a community)", compare_tool, "differences",
       _free_text_reasons)


def _expected_is_a_fault(*a, **k):
    r = _run_compare(*a, **k)
    r["differ"] += r["expected_differences"]
    r["identical"] = r["differ"] == 0
    return r


mutate(COMPARE, "the difference the decision 'חג לא נספר' makes is counted as a fault", compare_tool, "run", _expected_is_a_fault)

_compare_week = compare_tool.compare_week


def _reserve_not_looked_at(a, b, reserve, cards):
    row = _compare_week(a, b, reserve, cards)
    row["same_reserve"] = True
    row["same"] = row["same_order"] and row["same_in_turn"]
    return row


mutate(COMPARE, "the reserve is not compared", compare_tool, "compare_week", _reserve_not_looked_at)


def _order_not_looked_at(a, b, reserve, cards):
    row = _compare_week(a, b, reserve, cards)
    row["same_order"] = row["same_people"]
    row["same"] = row["same_people"] and row["same_reserve"] and row["same_in_turn"]
    return row


mutate(COMPARE, "the order of a list is not compared (only who is on it)", compare_tool, "compare_week", _order_not_looked_at)

_snapshot = compare_tool.snapshot


def _snapshot_through_sqlite(src, dest):
    import pathlib
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    a = sqlite3.connect(pathlib.Path(src).resolve().as_uri() + "?mode=ro", uri=True)
    b = sqlite3.connect(dest)
    try:
        a.backup(b)
    finally:
        b.close()
        a.close()


mutate(COMPARE, "the data file is opened with SQLite (which leaves working files beside it)", compare_tool, "snapshot",
       _snapshot_through_sqlite)

_read_pair = compare_tool._read_pair
mutate(COMPARE, "what the desktop program wrote last (its -wal file) is left out of the copy", compare_tool, "_read_pair",
       lambda src: (_read_pair(src)[0], b""))

mutate(COMPARE, "nobody checks that the sharing between computers is off for the copy", compare_tool, "assert_no_sync",
       lambda: None)

mutate(COMPARE, "only the site is asked who is marked for the holidays (seeing nobody passes for 'there is nobody')",
       compare_tool, "marks_agree", lambda site, desktop: True)

# ── the login of the server stage ─────────────────────────────────────────────
def _everyone_is_welcome(request):
    request.state.user = ""
    return None


mutate(AUTH, "with the login on, the site answers to anyone", webapp, "_refuse_stranger", _everyone_is_welcome)

_refuse = webapp._refuse_stranger


def _static_is_open(request):
    if request.url.path.startswith("/static/"):
        request.state.user = ""
        return None
    return _refuse(request)


mutate(AUTH, "the static files are served to anyone", webapp, "_refuse_stranger", _static_is_open)

mutate(AUTH, "one more address is open without a login", webapp, "OPEN_PATHS", webapp.OPEN_PATHS | {"/api/people"})

mutate(AUTH, "a site that answers to an outside name can be left without a login", config, "login_required",
       lambda: os.environ.get("HALUKA_WEB_LOGIN") == "1")

mutate(AUTH, "any password fits", auth, "verify_password", lambda password, stored: True)

mutate(AUTH, "the password itself is written to the users file", auth, "hash_password", lambda password: "scrypt$" + password)

mutate(AUTH, "wrong passwords are never counted (no lock)", auth, "locked_minutes", lambda conn, key, now: 0)

mutate(AUTH, "leaving only clears the browser's cookie (the session lives on in the server)", auth, "logout",
       lambda token: None)

mutate(AUTH, "a new password leaves the old sessions alive", auth, "end_sessions", lambda key: None)

mutate(AUTH, "a session never ends", auth, "SESSION_DAYS", 10 ** 5)

mutate(AUTH, "the server keeps the session itself, not its hash", auth, "_token_hash", lambda token: token)

mutate(AUTH, "a name is matched as typed (capital letters and extra spaces lock a user out)", auth, "_key",
       lambda name: str(name or ""))

class _Everyone(dict):
    def get(self, key, default=None):
        return {"name": "anyone"}


mutate(AUTH, "any Google account enters, allowed or not", auth, "google_allowed", lambda: _Everyone())

mutate(AUTH, "the way back from Google is not tied to the visit that started it (state, nonce)", google_login, "_same",
       lambda got, want: True)


class _AnyIssuer(tuple):
    def __contains__(self, item):
        return True


mutate(AUTH, "an answer that is not from Google is accepted", google_login, "ISSUERS", _AnyIssuer())

_claims = google_login._claims
mutate(AUTH, "an address Google did not verify is accepted", google_login, "_claims",
       lambda token: dict(_claims(token), email_verified=True))

mutate(AUTH, "an answer meant for another site is accepted", google_login, "_claims",
       lambda token: dict(_claims(token), aud="client-invented.apps.example"))

_settings = google_login.settings
mutate(AUTH, "the Google way works on an address that is not https", google_login, "settings",
       lambda: _settings() or ({"base": "x", "client_id": "c", "client_secret": "s", "redirect": "x"}
                               if os.environ.get("HALUKA_WEB_URL") else {}))

_person = auth._person
mutate(AUTH, "an account taken off the list keeps its open session", auth, "_person",
       lambda key: _person(key) or ({"name": "gone"} if key.startswith("g:") else None))

# ── the backup that leaves the server, and the readiness check ───────────────
mutate(SERVER, "the copy that arrived is never compared with the one that was sent", offsite, "_sha", lambda path: "same")

mutate(SERVER, "a folder inside the site's own data counts as 'off the server'", offsite, "_inside", lambda child, parent: False)

_to_folder = offsite._to_folder


def _invents_the_folder(src, folder):
    os.makedirs(folder, exist_ok=True)
    _to_folder(src, folder)


mutate(SERVER, "a drive that is not connected is quietly replaced by a new folder on the server", offsite, "_to_folder",
       _invents_the_folder)

mutate(SERVER, "a failed command is taken for a success", offsite, "_to_command", lambda src, cmd: None)

mutate(SERVER, "the copy is sent without checking that it can be restored", offsite.backup_service, "check", lambda path: {})

mutate(SERVER, "the screen is never told that the backup is late", offsite, "LATE_DAYS", 10 ** 6)

_status = offsite.status
mutate(SERVER, "on this computer the screen also speaks of the server's backup", offsite, "status",
       lambda now: dict(_status(now), show=True))

_checks = server_check.checks
mutate(SERVER, "the readiness check lets a server with the login off pass", server_check, "checks",
       lambda: [("OK" if "login is OFF" in text else level, text) for level, text in _checks()])

mutate(SERVER, "the readiness check does not look at who can read the files", server_check.stat, "S_IMODE", lambda mode: 0)

breaks = len(results) - BASELINES
if all(results):
    print(f"\nRESULT: ALL {breaks} BREAKS WERE CAUGHT — the website's tests bite ✓"
          + (f"   (only the ones that match {ONLY.pattern!r})" if ONLY else ""))
    sys.exit(0)
print(f"\nRESULT: {results.count(False)} of {breaks} breaks were NOT caught — strengthen the tests")
sys.exit(1)
