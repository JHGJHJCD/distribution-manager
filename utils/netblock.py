# -*- coding: utf-8 -*-
"""זיהוי חסימה של הסינון (נטפרי) — הודעה אחידה בכל התוכנה (v3.22).

נטפרי מחזיר HTTP 418 עם גוף "Blocked by NetFree" (חסימת דומיין או סריקת-תוכן).
עד עכשיו כל מודול הציג שגיאה כללית ("אין חיבור", "ההורדה נכשלה") והמפעיל לא
ידע אם זו הרשת או הסינון. כל מקום שתופס שגיאת-רשת שואל כאן:

    from utils import netblock
    msg = netblock.explain(exc) or "ההורדה נכשלה: ..."

מודול טהור (בלי Qt, בלי רשת). נבדק ב-test_tzintuk.py.
"""
import urllib.error

BLOCK_CODE = 418
# הודעה אחת, בשפה פשוטה, לכל המקומות.
NETFREE_MSG = ("נטפרי חסם את החיבור (קוד 418).\n"
               "זו לא תקלה ברשת ולא בתוכנה — הסינון חסם את הכתובת או את התוכן. "
               "יש לבקש מנטפרי לפתוח את הכתובת, ואז לנסות שוב.")


def _text_of(obj) -> str:
    """טקסט לבדיקה: הודעת החריגה + גוף התשובה (אם יש) + הסיבה הפנימית."""
    parts = []
    if isinstance(obj, (bytes, bytearray)):
        return obj[:400].decode("utf-8", errors="replace")
    if isinstance(obj, str):
        return obj
    if isinstance(obj, BaseException):
        parts.append(str(obj))
        reason = getattr(obj, "reason", None)
        if reason is not None and reason is not obj:
            parts.append(str(reason))
        body = getattr(obj, "_netfree_body", None)
        if body:
            parts.append(str(body))
        cause = getattr(obj, "__cause__", None) or getattr(obj, "__context__", None)
        if isinstance(cause, BaseException) and cause is not obj:
            parts.append(_text_of(cause))
    return " ".join(parts)


def is_blocked(obj) -> bool:
    """True כשהחריגה / הטקסט / גוף-התשובה נראים כמו חסימת נטפרי:
    HTTP 418, או "NetFree" / "Blocked by NetFree" בגוף או בהודעה."""
    if obj is None:
        return False
    if isinstance(obj, urllib.error.HTTPError) and getattr(obj, "code", None) == BLOCK_CODE:
        return True
    if isinstance(obj, int):
        return obj == BLOCK_CODE
    text = _text_of(obj).lower()
    return ("netfree" in text or "blocked by netfree" in text
            or "http error 418" in text or " 418" in text.split("(")[0][-6:])


def explain(obj, default: str = "") -> str:
    """ההודעה האחידה כשמדובר בחסימה, אחרת `default` (ברירת מחדל: '')."""
    return NETFREE_MSG if is_blocked(obj) else default


def wrap(exc: BaseException, body: bytes | str = "") -> BaseException:
    """מצמיד לחריגה את גוף התשובה (לזיהוי מאוחר) ומחזיר אותה — לשימוש
    במקומות שקוראים את הגוף לפני שמעלים מחדש."""
    try:
        exc._netfree_body = body[:400] if isinstance(body, (bytes, str)) else ""
    except Exception:
        pass
    return exc
