# -*- coding: utf-8 -*-
"""עזרי זמן משותפים — כל חותמות הזמן במערכת (סנכרון, הודעות) מוצגות ב**שעון
ישראל** (Asia/Jerusalem), בלי קשר לאזור-הזמן של המחשב. אם zoneinfo לא זמין
(EXE ללא tzdata) נופלים חזרה לשעון-המערכת — שאצל המשתמש ממילא מכוון לישראל."""
from datetime import datetime, timezone

_IL = None
_IL_TRIED = False


def _israel_zone():
    global _IL, _IL_TRIED
    if not _IL_TRIED:
        _IL_TRIED = True
        try:
            from zoneinfo import ZoneInfo
            _IL = ZoneInfo("Asia/Jerusalem")
        except Exception:
            _IL = None
    return _IL


def to_israel(iso: str):
    """Parse a UTC iso stamp → aware datetime in Israel time (or None)."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    z = _israel_zone()
    return dt.astimezone(z) if z is not None else dt.astimezone()


def clock(iso: str) -> str:
    """'HH:MM' in Israel time."""
    dt = to_israel(iso)
    return dt.strftime("%H:%M") if dt else ""


def datetime_str(iso: str) -> str:
    """'HH:MM · DD/MM/YYYY' in Israel time."""
    dt = to_israel(iso)
    return dt.strftime("%H:%M · %d/%m/%Y") if dt else ""


def relative(iso: str) -> str:
    """A short Hebrew 'how long ago' label ('עכשיו', 'לפני 5 דקות', 'לפני שעה',
    'אתמול', 'לפני 3 ימים', or a date)."""
    dt = to_israel(iso)
    if dt is None:
        return ""
    now = datetime.now(dt.tzinfo)
    sec = (now - dt).total_seconds()
    if sec < 0:
        sec = 0
    if sec < 45:
        return "עכשיו"
    if sec < 90:
        return "לפני דקה"
    minutes = int(sec // 60)
    if minutes < 60:
        return "לפני שתי דקות" if minutes == 2 else f"לפני {minutes} דקות"
    hours = int(sec // 3600)
    if hours < 24:
        if hours == 1:
            return "לפני שעה"
        if hours == 2:
            return "לפני שעתיים"
        return f"לפני {hours} שעות"
    days = int(sec // 86400)
    if days == 1:
        return "אתמול"
    if days == 2:
        return "לפני יומיים"
    if days < 7:
        return f"לפני {days} ימים"
    return dt.strftime("%d/%m/%Y")
