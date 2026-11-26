# -*- coding: utf-8 -*-
"""The recipients' cards — the rules of a card, pure (no database, no clock, no web).

What a card may hold and how it is written: the name is family-first ("משפחה פרטי"), the
status is only פעיל / מושהה, the kind of recipient is one of eight plain choices, and two
cards that look like the same person are only ever SUGGESTED for merging — never merged
by themselves, and the default answer is "two different people".

These rules mirror the desktop program's (database.normalize_status, split_full_name,
join_name, merge_fill_updates, find_duplicate_groups); `database.py` itself is not
imported here — the website has its own store.
"""
from .engine import holidays, selection

ACTIVE, SUSPENDED = "פעיל", "מושהה"
_LEGACY_ENDED = "הסתיים"
ONE_TIME = "חד-פעמי"
PHONE_SLOTS = ("phone1", "phone2", "phone3")

# The kind of recipient, as ONE choice on the card: key -> (label, frequency, priority).
# The priority numbers are never shown, only these words.
TYPES = [
    ("w1", "קבוע · שבועי", "שבועי", 4),
    ("w2", "קבוע · דו-שבועי", "דו-שבועי", 4),
    ("w3", "קבוע · תלת-שבועי", "תלת-שבועי", 4),
    ("w4", "קבוע · חודשי", "חודשי", 4),
    ("one1", "חד-פעמי · עדיפות ראשונה", ONE_TIME, 3),
    ("one2", "חד-פעמי · עדיפות שנייה", ONE_TIME, 2),
    ("one0", "חד-פעמי · מחכה לבירור", ONE_TIME, None),
    ("none", "כרטיס בלבד · לא מקבל", "", None),
]
_TYPE = {key: (label, freq, prio) for key, label, freq, prio in TYPES}
TYPE_LABEL = {key: label for key, label, _f, _p in TYPES}

# What the card screen shows and saves, in this order: (field, label, kind of value).
TEXT, PHONE, NUMBER, LONG = "text", "phone", "number", "long"
FIELDS = [
    ("last_name", "שם משפחה", TEXT), ("first_name", "שם פרטי", TEXT),
    ("phone1", "טלפון", PHONE), ("phone2", "טלפון 2", PHONE), ("phone3", "טלפון 3", PHONE),
    ("souls", "נפשות", NUMBER), ("children_total", "מספר ילדים", NUMBER),
    ("address", "כתובת", TEXT), ("id_number", "תעודת זהות", TEXT),
    ("spouse_id_number", "תעודת זהות בן/בת זוג", TEXT), ("email", "מייל", TEXT),
    ("synagogue", "בית כנסת", TEXT), ("representative", "נציג / קהילה", TEXT),
    ("income", "הכנסה", TEXT), ("per_soul", "פנוי לנפש", TEXT),
    ("housing_expenses", "הוצאות דיור", TEXT), ("medical_expenses", "הוצאות רפואיות", TEXT),
    ("notes", "הערות", LONG),
]
FIELD_LABEL = {f: label for f, label, _k in FIELDS}
_MAX_LEN = {TEXT: 200, PHONE: 40, LONG: 4000}
MAX_SOULS = 99


class Invalid(Exception):
    """What was typed cannot be saved; the message is shown to the user (Hebrew)."""


# ── small pure helpers ────────────────────────────────────────────────────────
def normalize_status(val) -> str:
    """Only פעיל or מושהה: empty -> active, the legacy 'הסתיים' -> suspended."""
    s = str(val or "").strip()
    if not s or s == "None":
        return ACTIVE
    return SUSPENDED if s in (_LEGACY_ENDED, SUSPENDED) else (ACTIVE if s == ACTIVE else s)


def split_full_name(full: str):
    """(first, last) of a FAMILY-FIRST name: the first word is the family name."""
    parts = (full or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[1:]), parts[0]


def join_name(first: str, last: str) -> str:
    """full_name = "משפחה פרטי" — the order identity, history and printing rely on."""
    return f"{' '.join((last or '').split())} {' '.join((first or '').split())}".strip()


def phone_key(p) -> str:
    """Digits only (a 9-digit number gets its leading 0) — when two phones are the same."""
    d = "".join(ch for ch in str(p or "") if ch.isdigit())
    return "0" + d if len(d) == 9 else d


def phones(rec: dict) -> list:
    """The card's numbers as typed, in slot order, no blanks, no repeats."""
    out, seen = [], set()
    for f in PHONE_SLOTS:
        v = str((rec or {}).get(f) or "").strip()
        k = phone_key(v)
        if k and k not in seen:
            seen.add(k)
            out.append(v)
    return out


def type_key(rec: dict) -> str:
    """Which of the eight choices a card is today."""
    freq = (rec.get("frequency") or "").strip()
    if freq == ONE_TIME:
        return {3: "one1", 2: "one2"}.get(rec.get("priority"), "one0")
    for key, _label, f, _p in TYPES[:4]:
        if freq == f:
            return key
    if selection.is_regular(rec):
        return "w1" if not freq else "other"       # a regular without a frequency = weekly
    return "none"


def type_label(rec: dict) -> str:
    key = type_key(rec)
    return TYPE_LABEL.get(key) or f"קבוע · {(rec.get('frequency') or '').strip()}"


# ── what was typed -> what is written ─────────────────────────────────────────
def clean(data: dict, existing: dict = None) -> dict:
    """The columns to write for a card that is being added (existing None) or changed.
    Raises Invalid with a sentence for the user. Only the fields that were sent are
    touched; the derived dates do not exist here at all, so nothing can write them."""
    out = {}
    for field, label, kind in FIELDS:
        if field not in data:
            continue
        raw = data[field]
        if kind == NUMBER:
            if raw in ("", None):
                out[field] = 0
                continue
            try:
                n = int(str(raw).strip())
            except ValueError:
                raise Invalid(f"{label}: צריך מספר שלם")
            if not 0 <= n <= MAX_SOULS:
                raise Invalid(f"{label}: צריך מספר בין 0 ל-{MAX_SOULS}")
            out[field] = n
            continue
        text = str(raw if raw is not None else "")
        text = text.replace("\r\n", "\n").strip() if kind == LONG else " ".join(text.split())
        if len(text) > _MAX_LEN[kind]:
            raise Invalid(f"{label}: ארוך מדי")
        if kind == PHONE and text and len(phone_key(text)) < 9:
            raise Invalid(f"{label}: מספר קצר מדי")
        out[field] = text

    if "first_name" in out or "last_name" in out or existing is None:
        first = out.get("first_name", (existing or {}).get("first_name") or "")
        last = out.get("last_name", (existing or {}).get("last_name") or "")
        full = join_name(first, last)
        if not full:
            raise Invalid("חסר שם")
        out["first_name"], out["last_name"], out["full_name"] = first, last, full

    # The holiday mark (stage 4): the general yes / no, and which holidays — none listed =
    # all of them. Ticked boxes only, never free text, so a mark cannot be misread.
    if "holiday_support" in data:
        if not isinstance(data["holiday_support"], (bool, int)):
            raise Invalid("נתמך חגים: צריך כן או לא")
        out["holiday_support"] = 1 if data["holiday_support"] else 0
    if "holidays" in data:
        names = data["holidays"]
        if not isinstance(names, (list, tuple)) or any(n not in holidays.HOLIDAYS for n in names):
            raise Invalid("נתמך חגים: חג לא מוכר")
        out["holidays"] = holidays.to_field(names)

    if "status" in data:
        status = normalize_status(data["status"])
        if status not in (ACTIVE, SUSPENDED):
            raise Invalid("סטטוס יכול להיות רק פעיל או מושהה")
        out["status"] = status
    elif existing is None:
        out["status"] = ACTIVE

    if "type" in data or existing is None:
        key = data.get("type") or "none"
        if key not in _TYPE:
            if existing is None or key != type_key(existing):
                raise Invalid("סוג המקבל לא מוכר")
        elif existing is None or key != type_key(existing):
            # the kind was really changed (an unchanged kind keeps its stored values as
            # they are, also an unusual pair that came from an import)
            _label, freq, prio = _TYPE[key]
            out["frequency"], out["priority"] = freq, prio
            out["priority_raw"] = "" if prio is None else str(prio)
    return out


def card_view(rec: dict) -> dict:
    """One card for the card screen (the only answer of the site, besides printing and
    Excel, that carries phones and personal details)."""
    first, last = (rec.get("first_name") or "").strip(), (rec.get("last_name") or "").strip()
    if join_name(first, last) != " ".join((rec.get("full_name") or "").split()):
        # the full name is the identity: a stored split that does not rebuild it is ignored,
        # so saving a card without touching the name can never change the name
        first, last = split_full_name(rec.get("full_name") or "")
    view = {f: ("" if rec.get(f) is None else rec.get(f)) for f, _l, _k in FIELDS}
    view.update(guid=rec["guid"], name=rec.get("full_name") or "", first_name=first, last_name=last,
                status=normalize_status(rec.get("status")), type=type_key(rec),
                type_label=type_label(rec), seen=rec.get("updated_at") or "",
                holiday_support=holidays.is_supported(rec), holidays=holidays.parse_list(rec.get("holidays")),
                holiday_names=list(holidays.HOLIDAYS))
    return view


def holiday_text(rec: dict) -> str:
    """'' / 'כל החגים' / 'סוכות, פסח' — the holiday mark in words."""
    return holidays.display(rec)


# ── search ────────────────────────────────────────────────────────────────────
def _norm(s) -> str:
    s = str(s or "").lower()
    for ch in "\"'׳״-־":
        s = s.replace(ch, "")
    return " ".join(s.split())


def matches(rec: dict, query: str) -> bool:
    """Every word of the query is somewhere in the card: name, address, mail, notes — and
    a number is also looked for in the phones and ID numbers, ignoring dashes and spaces."""
    words = _norm(query).split()
    if not words:
        return True
    text = _norm(" ".join(str(rec.get(f) or "") for f in
                          ("full_name", "first_name", "last_name", "address", "email",
                           "synagogue", "representative", "notes")))
    digits = " ".join(phone_key(rec.get(f)) for f in PHONE_SLOTS) + " " + " ".join(
        "".join(ch for ch in str(rec.get(f) or "") if ch.isdigit()) for f in ("id_number", "spouse_id_number"))
    for w in words:
        if w in text:
            continue
        if w.isdigit() and len(w) >= 3 and w in digits:
            continue
        return False
    return True


# ── look-alikes: a suggestion only ────────────────────────────────────────────
SAME_NAME, SAME_PHONE = "name", "phone"


def pair_key(a: str, b: str) -> tuple:
    return (a, b) if a <= b else (b, a)


def duplicate_groups(recipients: list, different=()) -> list:
    """Cards that share a full name, and phones that sit on more than one card:
    [{"type", "guids": [...]}]. `different` = pairs the manager already said are two
    different people; a group is left out once every pair in it was answered."""
    different = {pair_key(*p) for p in different}
    by_name, by_phone = {}, {}
    for r in recipients:
        name = " ".join((r.get("full_name") or "").split())
        if name:
            by_name.setdefault(name, []).append(r["guid"])
        for p in {phone_key(v) for v in phones(r)}:
            if len(p) >= 9:
                by_phone.setdefault(p, []).append(r["guid"])
    groups, seen = [], set()
    for kind, table in ((SAME_NAME, by_name), (SAME_PHONE, by_phone)):
        for key in sorted(table):
            members = sorted(set(table[key]))
            if len(members) < 2 or tuple(members) in seen:
                continue
            pairs = [pair_key(a, b) for i, a in enumerate(members) for b in members[i + 1:]]
            if all(p in different for p in pairs):
                continue
            seen.add(tuple(members))
            groups.append({"type": kind, "guids": members})
    return groups


def look_alikes(recipients: list, full_name: str, numbers: list, exclude: str = "") -> list:
    """Existing cards that carry this name or one of these phones (for the question that
    is asked before a new card is added)."""
    name = " ".join((full_name or "").split())
    keys = {phone_key(n) for n in numbers if len(phone_key(n)) >= 9}
    out = []
    for r in recipients:
        if r["guid"] == exclude:
            continue
        same_name = bool(name) and " ".join((r.get("full_name") or "").split()) == name
        same_phone = bool(keys & {phone_key(v) for v in phones(r)})
        if same_name or same_phone:
            out.append({"guid": r["guid"], "name": r.get("full_name") or "",
                        "same_name": same_name, "same_phone": same_phone})
    return out


def _blank(v) -> bool:
    return str(v if v is not None else "").strip() in ("", "0", "None")


def pick_keep(a: dict, b: dict, history_count: dict) -> tuple:
    """(keep, drop): the card with more history stays; a tie -> the older card."""
    def key(r):
        return (-history_count.get(r["guid"], 0), str(r.get("created_at") or ""), r["guid"])
    return (a, b) if key(a) <= key(b) else (b, a)


_NEVER_FILLED = {"full_name", "first_name", "last_name", "phone1", "phone2", "phone3", "notes",
                 "status", "priority", "priority_raw", "frequency", "last_dist_base",
                 "created_at", "updated_at", "holiday_support", "holidays"}


def merge_fill(keep: dict, drop: dict, columns: list) -> dict:
    """What to write on `keep` so it also carries what `drop` knows. Only EMPTY fields
    are filled — a value the kept card has is never replaced. The other card's phones go
    into free slots (the rest into the notes: no number is ever lost), its notes are
    appended, and the later 'last distribution' base wins."""
    fields = {}
    for f in columns:
        if f in _NEVER_FILLED:
            continue
        if not _blank(drop.get(f)) and _blank(keep.get(f)):
            fields[f] = drop.get(f)
    if type_key(keep) in ("none", "one0") and type_key(drop) not in ("none", "one0"):
        for f in ("frequency", "priority", "priority_raw"):
            fields[f] = drop.get(f)
    if not holidays.is_supported(keep) and holidays.is_supported(drop):
        # the mark and its list of holidays travel together (a list alone means nothing)
        fields["holiday_support"], fields["holidays"] = 1, str(drop.get("holidays") or "")
    base_drop = str(drop.get("last_dist_base") or "").strip()
    if len(base_drop) == 10 and base_drop > str(keep.get("last_dist_base") or "").strip():
        fields["last_dist_base"] = base_drop
    have = {phone_key(p) for p in phones(keep)}
    added = [p for p in phones(drop) if phone_key(p) not in have]
    free = [f for f in PHONE_SLOTS if not str(keep.get(f) or "").strip()]
    overflow = []
    for p in added:
        if free:
            fields[free.pop(0)] = p
        else:
            overflow.append(p)
    notes = str(keep.get("notes") or "").strip()
    for extra in (str(drop.get("notes") or "").strip(),
                  ("מספרים נוספים: " + ", ".join(overflow)) if overflow else ""):
        if extra and extra not in notes:
            notes = (notes + "\n" + extra).strip()
    if notes != str(keep.get("notes") or "").strip():
        fields["notes"] = notes
    return fields


def differences(a: dict, b: dict) -> list:
    """For the comparison before a merge: the fields where the two cards say different
    things — [{"label", "a", "b"}]. Names and phones are always listed."""
    out = [{"label": "שם", "a": a.get("full_name") or "", "b": b.get("full_name") or ""},
           {"label": "טלפונים", "a": " · ".join(phones(a)), "b": " · ".join(phones(b))},
           {"label": "סוג", "a": type_label(a), "b": type_label(b)},
           {"label": "סטטוס", "a": normalize_status(a.get("status")), "b": normalize_status(b.get("status"))}]
    if holiday_text(a) != holiday_text(b):
        out.append({"label": "נתמך חגים", "a": holiday_text(a) or "לא", "b": holiday_text(b) or "לא"})
    for f, label, kind in FIELDS:
        if f in ("first_name", "last_name") or kind == PHONE:
            continue
        va, vb = str(a.get(f) if a.get(f) is not None else "").strip(), str(b.get(f) if b.get(f) is not None else "").strip()
        if va != vb and not (_blank(va) and _blank(vb)):
            out.append({"label": label, "a": va, "b": vb})
    return out


def ids_differ(a: dict, b: dict) -> bool:
    """Two different ID numbers: a strong sign that these are two people."""
    def d(r, f):
        return "".join(ch for ch in str(r.get(f) or "") if ch.isdigit())
    return any(d(a, f) and d(b, f) and d(a, f) != d(b, f) for f in ("id_number", "spouse_id_number"))
