# -*- coding: utf-8 -*-
"""נתמך חגים — pure helpers (no DB, no Qt).

The kupa manager's request (mail thread "אשמח", 14–16/9/2026): a recipient can be
marked as supported for the holidays — BOTH a general yes/no mark AND a per-holiday
mark ("גם וגם"), and the mark must be filterable next to קבוע/ראשונה/שנייה.

Storage on the recipient row (additive migration, synced like every other field):
    holiday_support  INTEGER 0/1   — the general mark "נתמך חגים"
    holidays         TEXT          — comma-separated subset of HOLIDAYS, or '' =
                                     every holiday (only meaningful when the
                                     general mark is on)

Semantics: a person "supports holiday X" when the general mark is on AND the
subset is empty (= all holidays) or contains X. The general filter "נתמך חגים"
matches everyone with the mark on, whatever the subset.
"""

HOLIDAYS = ["ראש השנה", "סוכות", "חנוכה", "פורים", "פסח", "שבועות"]

SEP = ","


def parse_list(text) -> list:
    """'פסח, סוכות' → ['סוכות', 'פסח'] in HOLIDAYS order; unknown names dropped."""
    if not text:
        return []
    raw = [p.strip() for p in str(text).replace("،", ",").replace(";", ",").split(SEP)]
    names = {p for p in raw if p}
    return [h for h in HOLIDAYS if h in names]


def to_field(names) -> str:
    """Canonical stored form of a subset (HOLIDAYS order, comma-separated).
    Choosing every holiday is the same as choosing none = 'all'."""
    wanted = set(names or ())          # materialise once (callers pass generators)
    chosen = [h for h in HOLIDAYS if h in wanted]
    if len(chosen) == len(HOLIDAYS):
        return ""
    return SEP.join(chosen)


def is_supported(rec: dict) -> bool:
    """The general mark."""
    try:
        return bool(int(rec.get("holiday_support") or 0))
    except (TypeError, ValueError):
        return False


def supports(rec: dict, holiday: str = "") -> bool:
    """True when the recipient is holiday-supported; with a holiday name, only
    when that specific holiday is covered (empty subset = all)."""
    if not is_supported(rec):
        return False
    if not holiday:
        return True
    subset = parse_list(rec.get("holidays"))
    return not subset or holiday in subset


def display(rec: dict) -> str:
    """Short Hebrew text for tables/cards/Excel: '' / 'כל החגים' / 'פסח, סוכות'."""
    if not is_supported(rec):
        return ""
    subset = parse_list(rec.get("holidays"))
    return "כל החגים" if not subset else ", ".join(subset)


def from_text(text) -> tuple:
    """Inverse of display() for the Excel import: returns (holiday_support,
    holidays). Accepts 'כן'/'v'/'כל החגים'/'נתמך' as the general mark, a list of
    holiday names as the subset, anything else → not supported."""
    s = (str(text or "")).strip()
    if not s:
        return 0, ""
    subset = parse_list(s)
    if subset:
        return 1, to_field(subset)
    low = s.lower()
    if any(k in low for k in ("כן", "כל החגים", "נתמך", "v", "x", "✓", "1", "true")):
        return 1, ""
    return 0, ""
