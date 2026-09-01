# -*- coding: utf-8 -*-
"""שם חלוקה אוטומטי בעברית (#o2eft) — פרשת השבוע + תאריך עברי.

מודול טהור (בלי Qt/DB). מבוסס pyluach; אם הספרייה חסרה — מחזיר "" והקורא
נופל לפורמט הלועזי הישן.
"""
from datetime import date


def auto_weekly_name(d: date) -> str:
    """שם ברירת-מחדל לחלוקה שבועית בתאריך הנתון:
    "חלוקת פרשת נצבים — כ׳ אלול תשפ״ו", ובשבוע בלי פרשה (חג)
    "חלוקה שבועית — כ״ז אלול תשפ״ו". החזרת "" = אין נתון (fallback לקורא)."""
    try:
        from pyluach import dates, parshios
        g = dates.GregorianDate(d.year, d.month, d.day)
        heb = g.to_heb().hebrew_date_string()
        parsha = parshios.getparsha_string(g, israel=True, hebrew=True)
    except Exception:
        return ""
    if parsha:
        parsha = parsha.replace(", ", "־")     # "נצבים, וילך" → "נצבים־וילך"
        return f"חלוקת פרשת {parsha} — {heb}"
    return f"חלוקה שבועית — {heb}"
