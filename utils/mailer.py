# -*- coding: utf-8 -*-
"""מנוע המיילים למקבלים (v3.39) — מודול טהור (בלי Qt).

* placeholders — {שם}, {שם פרטי}, {תאריך חלוקה}, {פרשה} מוחלפים לכל נמען.
* build_targets — הופך רשימת מקבלים (+כתובות חיצוניות) לרשימת יעדים אחידה:
  כתובת תקינה אחת לכל אדם, בלי כפילויות, עם סיבת-דילוג למי שאין לו מייל.
* html_body — עוטף טקסט פשוט ב-HTML ימין-לשמאל עם כותרת/לוגו אופציונליים.
* send_batch — שולח אחד-אחד דרך email_utils.send_email (Google או SMTP),
  מדווח התקדמות ומחזיר דוח לכל נמען. רץ ב-thread מה-UI.
"""
import html
import re
from datetime import date

from utils import email_utils

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PLACEHOLDERS = (
    ("{שם}", "השם המלא של המקבל"),
    ("{שם פרטי}", "השם הפרטי בלבד"),
    ("{תאריך חלוקה}", "תאריך החלוקה הקרובה (מהמסך 'חלוקה ורישום')"),
    ("{פרשה}", "שם הפרשה של השבוע"),
)


def valid_email(addr: str) -> bool:
    return bool(EMAIL_RE.match((addr or "").strip()))


def render(text: str, rec: dict | None, ctx: dict | None = None) -> str:
    """החלפת placeholders. rec — כרטיס מקבל (או None לכתובת חיצונית)."""
    rec = rec or {}
    ctx = ctx or {}
    full = (rec.get("full_name") or "").strip()
    first = (rec.get("first_name") or "").strip()
    if not first and full:
        # full_name = "משפחה פרטי" (משפחה-קודם) — הפרטי הוא החלק השני
        parts = full.split(None, 1)
        first = parts[1] if len(parts) > 1 else parts[0]
    repl = {"{שם}": full or ctx.get("fallback_name", ""),
            "{שם פרטי}": first or full or ctx.get("fallback_name", ""),
            "{תאריך חלוקה}": ctx.get("dist_date", ""),
            "{פרשה}": ctx.get("parsha", "")}
    out = text or ""
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


def default_context(dist_iso: str = "") -> dict:
    """הקשר לרינדור — תאריך החלוקה בפורמט ישראלי + פרשה (pyluach אם קיים)."""
    ctx = {"dist_date": "", "parsha": ""}
    try:
        d = date.fromisoformat(dist_iso) if dist_iso else None
    except Exception:
        d = None
    if d:
        ctx["dist_date"] = d.strftime("%d/%m/%Y")
        try:
            from utils import hebdate
            name = hebdate.auto_weekly_name(d)      # "חלוקת פרשת X — תאריך"
            if name.startswith("חלוקת פרשת "):
                ctx["parsha"] = name[len("חלוקת פרשת "):].split(" — ")[0].strip()
        except Exception:
            pass
    return ctx


def build_targets(recs: list[dict], extra_addresses: list[str] | None = None) -> list[dict]:
    """יעדים: [{rec_id, guid, name, email, ok, reason}]. כתובת כפולה (אותו מייל
    לכמה כרטיסים / כתובת חיצונית שכבר קיימת) נשלחת פעם אחת."""
    seen = set()
    out = []
    for r in recs or []:
        email = (r.get("email") or "").strip()
        t = {"rec_id": r.get("id"), "guid": r.get("guid") or "",
             "name": r.get("full_name") or "", "email": email, "ok": False, "reason": ""}
        if not email:
            t["reason"] = "אין כתובת מייל בכרטיס"
        elif not valid_email(email):
            t["reason"] = "כתובת מייל לא תקינה"
        elif email.lower() in seen:
            t["reason"] = "אותה כתובת כבר ברשימה"
        else:
            t["ok"] = True
            seen.add(email.lower())
        out.append(t)
    for addr in extra_addresses or []:
        addr = (addr or "").strip()
        if not addr:
            continue
        t = {"rec_id": None, "guid": "", "name": addr, "email": addr, "ok": False,
             "reason": "", "external": True}
        if not valid_email(addr):
            t["reason"] = "כתובת מייל לא תקינה"
        elif addr.lower() in seen:
            t["reason"] = "אותה כתובת כבר ברשימה"
        else:
            t["ok"] = True
            seen.add(addr.lower())
        out.append(t)
    return out


def html_body(text: str, with_header: bool = True, org_name: str = "קופה של צדקה הר יונה") -> str:
    """טקסט פשוט → HTML RTL. שורות ריקות = פסקאות. with_header מוסיף רצועת
    כותרת עם הלוגו (cid:logo — email_utils מצרף אותו inline)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", (text or "").strip())]
    body = "".join(
        "<p style='margin:0 0 12px'>" + html.escape(p).replace("\n", "<br>") + "</p>"
        for p in paras if p)
    header = ""
    if with_header:
        # טבלה (לא flex) + width/height כאטריבוטים: מנוע ה-rich-text של Qt
        # (התצוגה המקדימה) מתעלם מ-CSS height על תמונה ומ-display:flex, וגם
        # לקוחות מייל (Gmail/Outlook) אמינים יותר עם טבלה.
        header = ("<table dir='rtl' width='100%' cellpadding='4' cellspacing='0' border='0'><tr>"
                  "<td width='56' align='right' valign='middle'>"
                  "<img src='cid:logo' alt='' width='44' height='44'></td>"
                  "<td align='right' valign='middle' style='font-size:18px;font-weight:700;"
                  f"color:#0f766e'>{html.escape(org_name)}</td>"
                  "</tr></table>"
                  "<hr style='border:none;border-top:2px solid #0f9d78;margin:0 0 16px'>")
    return ("<div dir='rtl' style=\"font-family:'Segoe UI',Arial,sans-serif;font-size:15px;"
            "color:#1e293b;line-height:1.6;max-width:640px;text-align:right\">"
            f"{header}{body}</div>")


def send_batch(targets: list[dict], subject: str, body_text: str, ctx: dict | None = None,
               attachment_path: str | None = None, logo_path: str | None = None,
               with_header: bool = True, rec_by_id: dict | None = None,
               progress=None, should_stop=None) -> list[dict]:
    """שולח לכל יעד ok=True. מחזיר דוח: [{rec_id, name, email, status: sent|failed,
    error}]. progress(done, total, last_row) נקרא אחרי כל נמען; should_stop() → True
    עוצר (מי שלא נשלח מסומן 'skipped')."""
    rows = []
    todo = [t for t in targets if t.get("ok")]
    total = len(todo)
    rec_by_id = rec_by_id or {}
    for i, t in enumerate(todo, 1):
        row = {"rec_id": t.get("rec_id"), "guid": t.get("guid", ""),
               "name": t.get("name", ""), "email": t.get("email", ""),
               "status": "sent", "error": ""}
        if should_stop and should_stop():
            row["status"] = "skipped"
            row["error"] = "השליחה נעצרה"
            rows.append(row)
            continue
        rec = rec_by_id.get(t.get("rec_id")) if t.get("rec_id") is not None else None
        c = dict(ctx or {}, fallback_name=t.get("name", ""))
        try:
            email_utils.send_email(
                t["email"], render(subject, rec, c),
                html_body(render(body_text, rec, c), with_header),
                attachment_path=attachment_path,
                inline_logo_path=logo_path if with_header else None)
        except Exception as e:
            row["status"] = "failed"
            row["error"] = str(e)
        rows.append(row)
        if progress:
            progress(i, total, row)
    return rows


def summarize(rows: list[dict]) -> tuple[int, int]:
    sent = sum(1 for r in rows if r.get("status") == "sent")
    failed = sum(1 for r in rows if r.get("status") == "failed")
    return sent, failed


STATUS_HE = {"sent": "נשלח", "failed": "נכשל", "skipped": "לא נשלח (נעצר)"}
