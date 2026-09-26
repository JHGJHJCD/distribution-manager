"""ערוץ הודעות מהמשתמש למפתח.

המשתמש משאיר הודעה דרך כפתור קטן בשורת המצב. ההודעה:
1. נשמרת תמיד מקומית — %APPDATA%\\ManhalHaluka\\feedback.jsonl (גיבוי שלא הולך
   לאיבוד גם בלי רשת).
2. מגיעה למפתח במייל בלבד (v3.64, #u7gmi — GitHub Issue וטופס Google הוסרו):
   • אם חשבון מייל מחובר (Google או SMTP) — נשלחת ישירות (`email_to_dev`).
   • אחרת — נפתחת תוכנת המייל של המשתמש עם ההודעה מוכנה (`mailto_link`).
3. נרשמת גם ב-DB (מסונכרן) — "הודעות שנשלחו" בהגדרות.
"""
import html
import os
import json
import urllib.parse
from datetime import datetime

import database as db

try:
    from version import APP_VERSION
except Exception:
    APP_VERSION = "?"

# Google Form submission endpoint + field ids (extracted from the public form).

FEEDBACK_PATH = os.path.join(db._data_dir(), "feedback.jsonl")


def _entry(message: str, name: str) -> dict:
    return {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": (name or "").strip(),
        "version": APP_VERSION,
        "os": f"{os.name}",
        "host": os.environ.get("COMPUTERNAME", ""),
        "message": message,
    }


def _save_local(entry: dict) -> None:
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def save_feedback(message: str, name: str = "") -> None:
    """שומר את ההודעה מקומית (סינכרוני) ובטבלת feedback שב-DB (v2.80, #ce6a0),
    כך שהיא מוצגת בתוך התוכנה (הגדרות ← הודעות שנשלחו) ומסונכרנת לשני המחשבים.
    #u7gmi (23/9/2026): הערוצים החיצוניים (GitHub Issue / טופס Google) הוסרו —
    ההודעה יוצאת למפתח **במייל בלבד** (`email_to_dev` / `mailto_link`)."""
    message = (message or "").strip()
    if not message:
        return
    entry = _entry(message, name)
    _save_local(entry)        # always — never lose a message
    try:
        db.add_feedback(message, author_name=entry["name"], host=entry["host"],
                        version=entry["version"])
    except Exception:
        pass                  # the JSONL copy is the safety net


def import_legacy_jsonl() -> int:
    """ייבוא חד-פעמי של הודעות ישנות מ-feedback.jsonl אל טבלת ה-DB (#ce6a0),
    כדי שגם דיווחים שנשלחו לפני v2.80 יופיעו במסך ההודעות. ה-guid נגזר
    דטרמיניסטית מהתוכן, כך שהרצה חוזרת (או ייבוא של אותו קובץ בשני מחשבים)
    לא יוצרת כפילויות. רץ פעם אחת פר-מחשב (דגל מקומי שלא מסונכרן)."""
    import uuid as _uuid
    try:
        if db.get_setting("feedback_legacy_imported"):
            return 0
    except Exception:
        return 0
    n = 0
    try:
        if os.path.exists(FEEDBACK_PATH):
            with open(FEEDBACK_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    body = (e.get("message") or "").strip()
                    if not body:
                        continue
                    guid = _uuid.uuid5(_uuid.NAMESPACE_URL,
                                       f"manhal-fb|{e.get('ts','')}|{e.get('host','')}|{body}").hex
                    if db.add_feedback(body, author_name=e.get("name", ""),
                                       host=e.get("host", ""),
                                       version=e.get("version", ""),
                                       guid=guid, created_at=e.get("ts", "")):
                        n += 1
        db.set_setting("feedback_legacy_imported", "1")
    except Exception:
        pass
    return n


# The developer's inbox — used by the optional "send a copy to my email" path in
# the feedback dialog (bug #20). Sending uses the app's own SMTP settings.
DEV_EMAIL = "xvxv99996@gmail.com"


def email_to_dev(message: str, name: str = "") -> tuple[bool, str]:
    """Send the feedback message straight to the developer's email using the
    configured SMTP account. Returns (ok, error_message). Synchronous so the
    dialog can tell the user whether it actually went out."""
    message = (message or "").strip()
    if not message:
        return False, "הודעה ריקה"
    try:
        from utils import email_utils
    except Exception as e:
        return False, str(e)
    if not email_utils.is_configured():
        return False, "שליחת מייל לא הוגדרה (ראה לשונית הגדרות ← מייל למתנדבים)."
    entry = _entry(message, name)
    esc = html.escape          # "<" in the user's text must not break the mail
    body = (
        "<div dir='rtl' style='font-family:Segoe UI,Arial;'>"
        "<p><b>התקבלה הודעה מהמשתמש:</b></p>"
        f"<p style='white-space:pre-wrap;'>{esc(message)}</p><hr>"
        f"<p style='color:#6b7280;font-size:12px;'>מאת: {esc(entry['name'] or 'אנונימי')} · "
        f"גרסה v{esc(str(entry['version']))} · {esc(entry['host'] or '—')} · {entry['ts']}</p></div>")
    try:
        email_utils.send_email(DEV_EMAIL, subject=MAIL_SUBJECT,
                               html_body=body)
        return True, ""
    except Exception as e:
        from utils import netblock
        return False, netblock.explain(e) or str(e)


MAIL_SUBJECT = "דיווח תקלה (מנהל חלוקה)"


def mailto_link(message: str = "", name: str = "") -> str:
    """mailto: URL to the developer with the subject 'דיווח תקלה (מנהל חלוקה)'
    and the message pre-filled — the fallback when no mail account is connected
    (#u7gmi): the user's own Gmail/mail app opens with everything ready."""
    entry = _entry(message or "", name)
    body = (message or "").strip()
    tail = f"\n\n— גרסה v{entry['version']} · {entry['host'] or ''} · {entry['ts']}"
    if entry["name"]:
        tail += f" · {entry['name']}"
    q = urllib.parse.urlencode({"subject": MAIL_SUBJECT, "body": body + tail},
                               quote_via=urllib.parse.quote)
    return f"mailto:{DEV_EMAIL}?{q}"
