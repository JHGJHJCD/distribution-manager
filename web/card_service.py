# -*- coding: utf-8 -*-
"""Stage 3 — the recipients: the list, one card, adding and changing, pausing, searching,
and the look-alike suggestions. Plain functions over a connection and the current time
(no web framework), like web/service.py.

Phones and personal details leave the store here only for ONE card that was opened
(`card`, `compare`); the list, the search and the suggestions carry names only.
"""
from datetime import datetime

from . import cards, config, planner, service, store
from .service import Refused

LOOK_AHEAD_WEEKS = 12          # how far the card looks for "when does he receive next"
LIST_LIMIT = 2000


def _row(r: dict, last: dict) -> dict:
    """A line of the list: no phone, no ID, no address, no notes."""
    return {"guid": r["guid"], "name": r.get("full_name") or "",
            "status": cards.normalize_status(r.get("status")),
            "type": cards.type_key(r), "type_label": cards.type_label(r),
            "souls": r.get("souls") or 0, "last": last.get(r["guid"]) or "",
            "holiday": cards.holiday_text(r)}


def card_list(conn, query: str = "", show: str = "all") -> dict:
    """Every card that matches the search (the search itself runs here, on the server, so
    a phone number can be looked for without any phone being sent to the screen)."""
    recipients = store.load_recipients(conn)
    last = store.last_received(conn)
    rows = [_row(r, last) for r in recipients if cards.matches(r, query)]
    if show == "active":
        rows = [r for r in rows if r["status"] == cards.ACTIVE]
    elif show == "paused":
        rows = [r for r in rows if r["status"] != cards.ACTIVE]
    elif show == "holiday":
        rows = [r for r in rows if r["holiday"]]
    groups = cards.duplicate_groups(recipients, store.different_pairs(conn))
    return {"cards": rows[:LIST_LIMIT], "found": len(rows), "total": len(recipients),
            "active": sum(1 for r in recipients if planner.is_active(r)),
            "duplicates": len(groups), "deleted": len([d for d in store.deleted_cards(conn)
                                                       if d["reason"] == "delete"]),
            "types": [{"key": k, "label": label} for k, label, _f, _p in cards.TYPES]}


def _coming(conn, now: datetime, guid: str) -> dict:
    """Where the card stands in the coming weeks — computed, like everything ahead."""
    ctx = service._context(conn, now)
    plan = service._plan(ctx, service.first_open_week(conn, now), LOOK_AHEAD_WEEKS)
    gets, waits = [], []
    for w in plan:
        if any(e["guid"] == guid for e in w["main"]):
            gets.append(w["date"].isoformat())
        elif any(e["guid"] == guid for e in w["reserve_list"]):
            waits.append(w["date"].isoformat())
    return {"weeks": LOOK_AHEAD_WEEKS, "receives": gets, "reserve": waits}


def card(conn, now: datetime, guid: str, db_path: str = None) -> dict:
    """One card in full, for the card screen."""
    service.roll_forward(conn, now, db_path)
    rec = store.get_recipient(conn, guid)
    if rec is None:
        raise Refused("הכרטיס לא נמצא")
    view = cards.card_view(rec)
    history = store.card_history(conn, guid)
    counts = store.history_counts(conn)
    view.update(history=[{"date": h["dist_date"], "received": bool(h["received"]),
                          "extra": (h["holiday"] or "").strip()} for h in history],
                history_count=counts.get(guid, 0), can_delete=counts.get(guid, 0) == 0,
                coming=_coming(conn, now, guid),
                why_out=("" if planner.is_active(rec) and planner.participation(rec)
                         else planner.why_not_participating(rec)))
    return view


def blank_card() -> dict:
    """What the 'new card' form starts from."""
    view = {f: "" for f, _l, _k in cards.FIELDS}
    view.update(guid="", name="", status=cards.ACTIVE, type="w1", seen="", souls="", children_total="",
                holiday_support=False, holidays=[], holiday_names=list(cards.holidays.HOLIDAYS))
    return view


def _alike_answer(alike: list, last: dict) -> list:
    return [dict(a, last=last.get(a["guid"]) or "") for a in alike]


_CHANGED_ELSEWHERE = "הכרטיס השתנה בינתיים במקום אחר. פתחו אותו שוב, ואז שנו."


def _unseen_version(seen: str, card: dict) -> bool:
    """The screen is saving over a version of the card it never showed."""
    return (seen or "") != (card.get("updated_at") or "")


def save(conn, now: datetime, data: dict, db_path: str = None) -> dict:
    """Add a card (no guid) or change one. Before a NEW card is written, an existing card
    with the same name or the same phone is pointed out and the user decides; the default
    is "two different people" (`sure` = the user said so). Nothing is ever merged here."""
    guid = (data.get("guid") or "").strip()
    try:
        if guid:
            existing = store.get_recipient(conn, guid)
            if existing is None:
                raise Refused("הכרטיס לא נמצא (אולי נמחק או אוחד בינתיים)")
            if _unseen_version(data.get("seen"), existing):
                raise Refused(_CHANGED_ELSEWHERE)
            fields = cards.clean(data, existing)
        else:
            existing = None
            fields = cards.clean(data, None)
    except cards.Invalid as e:
        raise Refused(str(e))

    alike = []
    if existing is None:
        alike = cards.look_alikes(store.load_recipients(conn), fields["full_name"],
                                  [fields.get(f, "") for f in cards.PHONE_SLOTS])
        if alike and not data.get("sure"):
            return {"ok": False, "alike": _alike_answer(alike, store.last_received(conn))}
    with store.tx(conn):
        if existing is None:
            guid = store.insert_recipient(conn, fields, now)
            for a in alike:          # the user answered "two different people": not asked again
                store.set_different(conn, [guid, a["guid"]], now)
        else:
            if _unseen_version(data.get("seen"), store.get_recipient(conn, guid) or {}):
                raise Refused(_CHANGED_ELSEWHERE)      # changed between the check and the write
            store.update_recipient(conn, guid, fields, now)
    return {"ok": True, "guid": guid, "new": existing is None}


def set_status(conn, now: datetime, guid: str, status: str) -> dict:
    """Pause a card or bring it back. A paused card is on no list; nothing else changes."""
    status = cards.normalize_status(status)
    if status not in (cards.ACTIVE, cards.SUSPENDED):
        raise Refused("סטטוס יכול להיות רק פעיל או מושהה")
    with store.tx(conn):
        if store.get_recipient(conn, guid) is None:
            raise Refused("הכרטיס לא נמצא")
        store.update_recipient(conn, guid, {"status": status}, now)
    return {"ok": True, "status": status}


def delete(conn, now: datetime, guid: str, db_path: str = None) -> dict:
    """Only a card that never received anything can be deleted (and it can be brought
    back). A card with history is paused instead."""
    if db_path:
        store.backup(db_path, config.backup_dir(), "before-delete-card", now)
    try:
        with store.tx(conn):
            store.delete_recipient(conn, guid, now)
    except LookupError:
        raise Refused("הכרטיס לא נמצא")
    except ValueError:
        raise Refused("לכרטיס הזה יש היסטוריה של חלוקות, ולכן אי אפשר למחוק אותו. אפשר להשהות אותו.")
    return {"ok": True}


def deleted(conn) -> dict:
    return {"cards": [{"guid": d["guid"], "name": d["name"], "deleted_at": d["deleted_at"][:10]}
                      for d in store.deleted_cards(conn) if d["reason"] == "delete"]}


def restore(conn, now: datetime, guid: str) -> dict:
    try:
        with store.tx(conn):
            store.restore_recipient(conn, guid, now)
    except LookupError:
        raise Refused("הכרטיס לא נמצא ברשימת המחוקים")
    except ValueError:
        raise Refused("הכרטיס כבר קיים")
    return {"ok": True, "guid": guid}


# ── look-alikes ───────────────────────────────────────────────────────────────
_GROUP_TITLE = {cards.SAME_NAME: "אותו שם", cards.SAME_PHONE: "אותו מספר טלפון"}


def duplicates(conn) -> dict:
    """The suggestions: groups of cards with the same name or the same phone that were not
    answered yet. Names only (the phone itself is not sent — only that it is shared)."""
    recipients = store.load_recipients(conn)
    by_guid = {r["guid"]: r for r in recipients}
    last, counts = store.last_received(conn), store.history_counts(conn)
    groups = []
    for g in cards.duplicate_groups(recipients, store.different_pairs(conn)):
        groups.append({"type": g["type"], "title": _GROUP_TITLE[g["type"]],
                       "members": [dict(_row(by_guid[x], last), history_count=counts.get(x, 0))
                                   for x in g["guids"]]})
    return {"groups": groups}


def _pair(conn, a: str, b: str):
    ra, rb = store.get_recipient(conn, a), store.get_recipient(conn, b)
    if a == b or ra is None or rb is None:
        raise Refused("אחד הכרטיסים כבר לא קיים")
    return ra, rb


def compare(conn, a: str, b: str) -> dict:
    """Two cards side by side before a merge: which one would stay, what differs, and what
    the kept card would gain. (Opened cards: phones and details are shown.)"""
    ra, rb = _pair(conn, a, b)
    counts = store.history_counts(conn)
    keep, drop = cards.pick_keep(ra, rb, counts)
    gain = cards.merge_fill(keep, drop, store.RECIPIENT_COLUMNS)
    labels = dict(cards.FIELD_LABEL, frequency="סוג", last_dist_base="חלוקה אחרונה", holiday_support="נתמך חגים")
    return {"keep": {"guid": keep["guid"], "name": keep.get("full_name") or "",
                     "history_count": counts.get(keep["guid"], 0)},
            "drop": {"guid": drop["guid"], "name": drop.get("full_name") or "",
                     "history_count": counts.get(drop["guid"], 0)},
            "differences": [{"label": d["label"], "keep": d["a"], "drop": d["b"]}
                            for d in cards.differences(keep, drop)],
            "ids_differ": cards.ids_differ(ra, rb),
            "gains": sorted({labels[f] for f in gain if f in labels})}


def set_different(conn, now: datetime, guids: list) -> dict:
    """The default answer to a suggestion: these are different people. Nothing changes in
    any card; the suggestion just stops appearing."""
    guids = [g for g in dict.fromkeys(guids) if store.get_recipient(conn, g) is not None]
    if len(guids) < 2:
        raise Refused("צריך לפחות שני כרטיסים")
    with store.tx(conn):
        store.set_different(conn, guids, now)
    return {"ok": True}


def merge(conn, now: datetime, keep_guid: str, drop_guid: str, db_path: str = None) -> dict:
    """Merge two cards — only ever on an explicit request for exactly this pair, with the
    card that stays named by the user's screen (it must be the one `compare` showed).
    A backup is taken first; the merged-away card is kept whole in deleted_cards."""
    ra, rb = _pair(conn, keep_guid, drop_guid)
    keep, drop = cards.pick_keep(ra, rb, store.history_counts(conn))
    if keep["guid"] != keep_guid:
        raise Refused("הכרטיסים השתנו בינתיים. פתחו את ההשוואה שוב.")
    if db_path:
        store.backup(db_path, config.backup_dir(), "before-merge-cards", now)
    with store.tx(conn):
        keep, drop = _pair(conn, keep_guid, drop_guid)
        fields = cards.merge_fill(keep, drop, store.RECIPIENT_COLUMNS)
        moved = store.merge_recipients(conn, keep_guid, drop_guid, fields, now)
    return {"ok": True, "guid": keep_guid, "moved": moved}
