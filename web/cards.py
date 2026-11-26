# -*- coding: utf-8 -*-
"""The cards screen (stage 3): the list, one card, adding, editing, pausing, and pointing
out cards that may be the same person twice.

The rules are the desktop program's (tabs/recipients.py: RecipientDialog, database.py):
  * the name is kept as "family first" (full_name) — the one identity of a card;
  * a phone is 0 + 8 or 9 digits (spaces, dashes, brackets and '+' are allowed around them);
  * status is only פעיל / מושהה;
  * the kind is chosen in ONE box — קבוע (with a schedule) / first priority / second
    priority / none / "to be clarified" — and the stored priority + frequency follow it;
  * money fields are kept as typed (0 = unknown, a minus = debt — the score reads them);
  * two cards with one name are never merged by themselves: adding one asks first.
Nothing here decides who receives: that stays in selection.py, which reads the saved card.

No web framework and no clock in this module: functions take a connection and `now`.
"""
import re
from datetime import datetime

from . import planner, store
from .engine import selection

ACTIVE, PAUSED = "פעיל", "מושהה"
ONE_TIME = planner.ONE_TIME
SCHEDULES = tuple(selection.FREQUENCY_INTERVAL_DAYS)            # שבועי / דו-שבועי / תלת-שבועי / חודשי
CHECK_RAW = "חובת בירור"
# the one "kind" box of the card -> what is stored
KIND_REGULAR, KIND_FIRST, KIND_SECOND, KIND_NONE, KIND_CHECK = "regular", "first", "second", "none", "check"
KIND_LABEL = {KIND_REGULAR: "קבוע", KIND_FIRST: "עדיפות ראשונה", KIND_SECOND: "עדיפות שנייה",
              KIND_NONE: "ללא", KIND_CHECK: CHECK_RAW}
_KIND_PRIORITY = {KIND_REGULAR: 4, KIND_FIRST: 3, KIND_SECOND: 2, KIND_NONE: None, KIND_CHECK: None}

TEXT_FIELDS = {          # field -> longest text accepted
    "phone1": 20, "phone2": 20, "phone3": 20, "address": 120, "notes": 2000, "id_number": 12,
    "spouse_id_number": 12, "marital_status": 30, "email": 120, "synagogue": 60, "occupation": 60,
    "work_scope": 30, "parent_type": 30, "housing_expenses": 20, "medical_expenses": 20, "income": 20,
    "per_soul": 20, "external_id": 30, "source": 60, "representative": 60,
}
INT_FIELDS = {"souls": 99, "children_home": 30, "children_married": 30, "children_total": 30}
DATE_FIELDS = ("birth_date", "spouse_birth_date")
PHONES = ("phone1", "phone2", "phone3")
# what the card form reads and writes (besides the name parts and the kind box)
FORM_FIELDS = tuple(TEXT_FIELDS) + tuple(INT_FIELDS) + DATE_FIELDS + ("status", "holiday_support")
FIELD_LABEL = {
    "*": "", "full_name": "שם", "first_name": "שם פרטי", "last_name": "משפחה", "status": "סטטוס",
    "frequency": "תדירות", "priority": "עדיפות", "priority_raw": "עדיפות", "souls": "נפשות",
    "phone1": "טלפון", "phone2": "טלפון נוסף", "phone3": "טלפון נוסף", "address": "כתובת", "notes": "הערות",
    "holiday_support": "חגים", "birth_date": "ת. לידה בעל", "spouse_birth_date": "ת. לידה אשה",
    "id_number": "ת.ז. בעל", "spouse_id_number": "ת.ז. אשה", "marital_status": "מצב אישי", "email": "אימייל",
    "synagogue": "בית כנסת", "occupation": "עיסוק בעל", "work_scope": "היקף משרה", "parent_type": "סוג הורה",
    "children_home": "ילדים בבית", "children_married": "ילדים נשואים", "children_total": "מספר ילדים",
    "housing_expenses": "הוצאות דיור", "medical_expenses": "הוצאות רפואיות", "income": "הכנסות",
    "per_soul": "פנוי לנפש", "external_id": "מס' מזהה", "source": "מקור", "representative": "שם נציג",
}
_PRIORITY_TEXT = {"4": "קבוע", "3": "עדיפות ראשונה", "2": "עדיפות שנייה", "": "ללא"}
_PHONE_RE = re.compile(r"0\d{8,9}")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class Refused(Exception):
    """A request that cannot be carried out; the message is shown to the user (Hebrew).
    `fields`: {field: what is wrong with it}; `duplicates`: cards that may be the same person."""

    def __init__(self, message, fields=None, duplicates=None, code="refused"):
        super().__init__(message)
        self.fields, self.duplicates, self.code = fields or {}, duplicates or [], code


# ── small pure helpers ────────────────────────────────────────────────────────
def join_name(first: str, last: str) -> str:
    """'family first' — the same order as the desktop program (never change it)."""
    return " ".join(p for p in ((last or "").strip(), (first or "").strip()) if p)


def name_parts(rec: dict) -> tuple:
    """(first, last) of a card: the stored parts, else split from full_name (first word =
    family; a single word = first name) — as database.split_full_name."""
    first, last = (rec.get("first_name") or "").strip(), (rec.get("last_name") or "").strip()
    if first or last:
        return first, last
    words = (rec.get("full_name") or "").split()
    if len(words) <= 1:
        return (words[0] if words else ""), ""
    return " ".join(words[1:]), words[0]


def phone_key(text) -> str:
    """Digits only, for comparing two phones ('' when it is not a phone)."""
    digits = re.sub(r"\D", "", str(text or ""))
    if len(digits) == 9 and not digits.startswith("0"):
        digits = "0" + digits
    return digits if len(digits) >= 9 else ""


def phone_ok(text: str) -> bool:
    return bool(_PHONE_RE.fullmatch(re.sub(r"[\s\-()+]", "", text)))


def kind_of(rec: dict) -> str:
    """Which choice of the 'kind' box a stored card shows."""
    if selection.is_regular(rec):
        return KIND_REGULAR
    p = rec.get("priority")
    if p == 3:
        return KIND_FIRST
    if p == 2:
        return KIND_SECOND
    return KIND_CHECK if (rec.get("priority_raw") or "").strip() == CHECK_RAW else KIND_NONE


def schedule_of(rec: dict) -> str:
    freq = (rec.get("frequency") or "").strip()
    return freq if freq in SCHEDULES else ""


def kind_text(rec: dict) -> str:
    """'דו-שבועי' / 'חד-פעמי · עדיפות ראשונה' / 'ללא' — for the list."""
    kind = kind_of(rec)
    if kind == KIND_REGULAR:
        return schedule_of(rec) or "קבוע"
    if kind in (KIND_FIRST, KIND_SECOND):
        return f"{ONE_TIME} · {KIND_LABEL[kind]}"
    return KIND_LABEL[kind]


# ── cleaning what the form sends ──────────────────────────────────────────────
def clean(data: dict, current: dict = None) -> dict:
    """Check what the card form sent and turn it into card columns. Raises Refused with a
    sentence per wrong field. `current`: the stored card when editing — fields the form did
    not send stay as they are, and the kind / schedule are rewritten only when the user
    really chose another one (an old card with an unusual combination is not "fixed" by
    opening and saving it)."""
    errors, out = {}, {}
    data = dict(data or {})

    def text(key):
        v = data.get(key)
        return "" if v is None else str(v).strip()

    # the name
    if "first_name" in data or "last_name" in data or current is None:
        first, last = text("first_name"), text("last_name")
        full = join_name(first, last)
        if not first:
            errors["first_name"] = "חסר שם פרטי"
        elif not 2 <= len(full) <= 60:
            errors["first_name"] = "השם המלא צריך להיות בין 2 ל-60 אותיות"
        out.update(first_name=first, last_name=last, full_name=full)

    for key, longest in TEXT_FIELDS.items():
        if key not in data:
            continue
        v = text(key)
        if len(v) > longest:
            errors[key] = f"ארוך מדי (עד {longest} תווים)"
        elif key in PHONES and v and not phone_ok(v):
            errors[key] = "מספר טלפון צריך להתחיל ב-0 ולהיות באורך 9 או 10 ספרות"
        elif key == "email" and v and not _EMAIL_RE.fullmatch(v):
            errors[key] = "כתובת המייל לא נראית תקינה"
        out[key] = v
    for key, most in INT_FIELDS.items():
        if key not in data:
            continue
        v = data.get(key)
        v = 0 if v in ("", None) else v
        if isinstance(v, str) and re.fullmatch(r"\d{1,3}", v.strip()):
            v = int(v.strip())
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= most:
            errors[key] = f"צריך מספר שלם בין 0 ל-{most}"
        else:
            out[key] = v
    for key in DATE_FIELDS:
        if key not in data:
            continue
        v = text(key)
        if v and not planner.valid_iso(v):
            errors[key] = "תאריך לא תקין"
        out[key] = v
    if "status" in data or current is None:
        status = text("status") or ACTIVE
        if status not in (ACTIVE, PAUSED):
            errors["status"] = "סטטוס יכול להיות רק פעיל או מושהה"
        out["status"] = status
    if "holiday_support" in data:
        out["holiday_support"] = 1 if data.get("holiday_support") in (True, 1, "1") else 0

    # the kind box (+ the schedule of a קבוע)
    if "kind" in data or current is None:
        kind, schedule = text("kind") or KIND_REGULAR, text("schedule")
        if kind not in _KIND_PRIORITY:
            errors["kind"] = "סוג לא מוכר"
        elif kind == KIND_REGULAR and schedule not in SCHEDULES:
            errors["schedule"] = "לקבוע צריך לבחור תדירות"
        elif current is None or kind != kind_of(current) or (kind == KIND_REGULAR and schedule != schedule_of(current)):
            out["priority"] = _KIND_PRIORITY[kind]
            out["frequency"] = schedule if kind == KIND_REGULAR else ONE_TIME if kind in (KIND_FIRST, KIND_SECOND) else ""
            out["priority_raw"] = CHECK_RAW if kind == KIND_CHECK else KIND_LABEL[kind] if kind != KIND_NONE else ""
    if errors:
        raise Refused("יש שדות שצריך לתקן", fields=errors, code="invalid")
    return out


# ── may be the same person twice ──────────────────────────────────────────────
def lookalikes(conn, fields: dict, exclude_guid: str = None) -> list:
    """Cards that may be the same person as `fields`: the same full name, or a shared phone.
    Only pointed out — two cards are never merged by themselves."""
    name = (fields.get("full_name") or "").strip()
    keys = {phone_key(fields.get(k)) for k in PHONES} - {""}
    out = []
    for r in store.load_recipients(conn):
        if r["guid"] == exclude_guid:
            continue
        same_name = bool(name) and (r.get("full_name") or "").strip() == name
        shared = keys & ({phone_key(r.get(k)) for k in PHONES} - {""})
        if same_name or shared:
            out.append({"guid": r["guid"], "name": r.get("full_name") or "", "status": r.get("status") or "",
                        "why": "אותו שם" + (" ואותו טלפון" if shared else "") if same_name else "אותו טלפון"})
    return out


def duplicate_groups(conn) -> list:
    """Every group of cards that may be one person: [{why, key, cards: [{guid, name, status}]}]."""
    by_name, by_phone = {}, {}
    for r in store.load_recipients(conn):
        card = {"guid": r["guid"], "name": r.get("full_name") or "", "status": r.get("status") or ""}
        name = (r.get("full_name") or "").strip()
        if name:
            by_name.setdefault(name, []).append(card)
        for key in {phone_key(r.get(k)) for k in PHONES} - {""}:
            by_phone.setdefault(key, []).append(card)
    groups = [{"why": "שם כפול", "key": k, "cards": v} for k, v in sorted(by_name.items()) if len(v) > 1]
    seen = {tuple(sorted(c["guid"] for c in g["cards"])) for g in groups}
    for key, cards in sorted(by_phone.items()):
        ids = tuple(sorted(c["guid"] for c in cards))
        if len(cards) > 1 and ids not in seen:
            seen.add(ids)
            groups.append({"why": "טלפון משותף", "key": key, "cards": cards})
    return groups


# ── answers for the page ──────────────────────────────────────────────────────
def card_list(conn) -> dict:
    """Every card, for the list: the name, the kind, the status, the first phone, the souls.
    (Phones leave the store here because this IS the address book; the weeks' screen still
    gets none.)"""
    rows = [{"guid": r["guid"], "name": r.get("full_name") or "", "status": r.get("status") or "",
             "kind": kind_of(r), "kind_text": kind_text(r), "phone": (r.get("phone1") or "").strip(),
             "souls": r.get("souls") or 0, "takes_part": bool(planner.is_active(r) and planner.participation(r))}
            for r in store.load_recipients(conn)]
    return {"cards": rows, "duplicates": len(duplicate_groups(conn)),
            "kinds": [{"value": k, "label": v} for k, v in KIND_LABEL.items()], "schedules": list(SCHEDULES)}


def _change_text(field: str, value: str) -> str:
    if field == "priority":
        return _PRIORITY_TEXT.get(value, value)
    if field == "holiday_support":
        return "כן" if value == "1" else "לא"
    return value


def _card(conn, rec: dict) -> dict:
    first, last = name_parts(rec)
    card = {"guid": rec["guid"], "updated_at": rec.get("updated_at") or "", "name": rec.get("full_name") or "",
            "first_name": first, "last_name": last, "kind": kind_of(rec), "schedule": schedule_of(rec),
            "created_at": (rec.get("created_at") or "")[:10]}
    for key in FORM_FIELDS:
        card[key] = rec.get(key) if key in INT_FIELDS else 1 if key == "holiday_support" and rec.get(key) else \
            0 if key == "holiday_support" else rec.get(key) or ""
    received = [r["dist_date"] for r in conn.execute(
        "SELECT dist_date FROM history WHERE recipient_guid=? AND received=1 ORDER BY dist_date DESC", (rec["guid"],))]
    card["received_count"], card["last_received"] = len(received), received[0] if received else ""
    card["changes"] = [{"at": c["changed_at"][:16], "field": FIELD_LABEL.get(c["field"], c["field"]),
                        "old": _change_text(c["field"], c["old"]), "new": _change_text(c["field"], c["new"])}
                       for c in store.load_changes(conn, rec["guid"]) if c["field"] not in ("priority_raw", "full_name")]
    card["lookalikes"] = lookalikes(conn, rec, rec["guid"])
    return card


def get_card(conn, guid: str) -> dict:
    rec = store.get_recipient(conn, guid)
    if rec is None:
        raise Refused("הכרטיס לא נמצא", code="missing")
    return _card(conn, rec)


def add_card(conn, now: datetime, data: dict, confirmed: bool = False) -> dict:
    """A new card. When a card with the same name or phone already exists the request is
    refused with the look-alikes, unless the user confirmed these are different people."""
    fields = clean(data)
    twins = lookalikes(conn, fields)
    if twins and not confirmed:
        raise Refused("כבר יש כרטיס שנראה כמו אותו אדם", duplicates=twins, code="duplicate")
    with store.tx(conn):
        guid = store.insert_recipient(conn, fields, now)
    return get_card(conn, guid)


def save_card(conn, now: datetime, guid: str, data: dict, seen_updated_at: str = None) -> dict:
    """Save an edited card. `seen_updated_at`: the card's stamp when the form was opened —
    when the card was changed since (another tab), nothing is written and the user is told."""
    with store.tx(conn):
        current = store.get_recipient(conn, guid)
        if current is None:
            raise Refused("הכרטיס לא נמצא", code="missing")
        if seen_updated_at is not None and seen_updated_at != (current.get("updated_at") or ""):
            raise Refused("הכרטיס השתנה מאז שנפתח. טענתי אותו מחדש; בדקו ושמרו שוב.", code="stale")
        changed = store.update_recipient(conn, guid, clean(data, current), now)
    card = get_card(conn, guid)
    card["changed"] = len(changed)
    return card
