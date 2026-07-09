"""ערוץ הודעות מהמשתמש למפתח.

המשתמש משאיר הודעה דרך כפתור קטן בשורת המצב. ההודעה:
1. נשמרת תמיד מקומית — %APPDATA%\\ManhalHaluka\\feedback.jsonl (גיבוי שלא הולך
   לאיבוד גם בלי רשת).
2. נשלחת ברקע לערוץ המקוון:
   • אם הוגדר טוקן GitHub (utils/_secret.py או משתני-סביבה) — נפתח Issue חדש
     במאגר. כך כל דיווח מגיע ישירות לרשימת התקלות בגיטאב.
   • אחרת — נשלחת לטופס Google (ללא טוקן), והדיווחים נאספים בגיליון התשובות.

הטוקן לעולם לא נשמר בקוד המשותף: הוא יושב ב-utils/_secret.py שנמצא ב-.gitignore
ונכנס רק לתוך ה-EXE בזמן הבנייה. כתובת הטופס ומזהי השדות ציבוריים ולכן כאן.
"""
import os
import json
import threading
import urllib.parse
import urllib.request
from datetime import datetime

import database as db

try:
    from version import APP_VERSION
except Exception:
    APP_VERSION = "?"

# Google Form submission endpoint + field ids (extracted from the public form).
GFORM_URL = ("https://docs.google.com/forms/d/e/"
             "1FAIpQLScYbu4ziy7l558_RP6w48Bjt9vpHv-wf1l4OfBUlmDKKN2-Vg/formResponse")
GFORM_FIELD_MESSAGE = "entry.1847752553"
GFORM_FIELD_NAME = "entry.2127661925"

FEEDBACK_PATH = os.path.join(db._data_dir(), "feedback.jsonl")


def _github_config() -> tuple[str, str]:
    """(token, 'owner/repo') for GitHub Issue posting, or ('', '') if unset.

    Read from the gitignored utils/_secret.py first (bundled into the EXE at
    build time), then from environment variables as a dev fallback. Any import
    error just means "not configured" — the caller falls back to the form.
    """
    token = repo = ""
    try:
        from utils import _secret  # gitignored — present only in real builds
        token = getattr(_secret, "GH_FEEDBACK_TOKEN", "") or ""
        repo = getattr(_secret, "GH_FEEDBACK_REPO", "") or ""
    except Exception:
        pass
    token = token or os.environ.get("GH_FEEDBACK_TOKEN", "")
    repo = repo or os.environ.get("GH_FEEDBACK_REPO", "")
    return token.strip(), repo.strip()


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


def _post_google_form(entry: dict) -> bool:
    """Submit the feedback to the Google Form. Best-effort — any failure is
    swallowed (the local copy is the safety net)."""
    # Fold version/host into the message so they show up in the responses sheet.
    msg = (f"{entry['message']}\n\n"
           f"[v{entry['version']} · {entry['host'] or '—'} · {entry['ts']}]")
    data = urllib.parse.urlencode({
        GFORM_FIELD_MESSAGE: msg,
        GFORM_FIELD_NAME: entry["name"],
    }).encode("utf-8")
    req = urllib.request.Request(
        GFORM_URL, data=data, method="POST",
        headers={"User-Agent": "ManhalHaluka-Feedback",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _post_github_issue(entry: dict) -> bool:
    """Open a GitHub Issue for the feedback. Best-effort — any failure is
    swallowed (the local copy is the safety net)."""
    token, repo = _github_config()
    if not token or not repo:
        return False
    name = entry["name"] or "אנונימי"
    title = f"משוב: {entry['message'][:60].splitlines()[0]}"
    body = (f"{entry['message']}\n\n"
            f"---\n"
            f"- מאת: {name}\n"
            f"- גרסה: v{entry['version']}\n"
            f"- מחשב: {entry['host'] or '—'}\n"
            f"- תאריך: {entry['ts']}\n")
    data = json.dumps({"title": title, "body": body,
                       "labels": ["feedback"]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues", data=data, method="POST",
        headers={"User-Agent": "ManhalHaluka-Feedback",
                 "Accept": "application/vnd.github+json",
                 "Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _send_online(entry: dict) -> None:
    """Send to GitHub if configured, otherwise fall back to the Google Form."""
    if _post_github_issue(entry):
        return
    _post_google_form(entry)


def save_feedback(message: str, name: str = "") -> None:
    """שומר את ההודעה מקומית (סינכרוני) ושולח ברקע לגיטאב/טופס Google."""
    message = (message or "").strip()
    if not message:
        return
    entry = _entry(message, name)
    _save_local(entry)        # always — never lose a message
    threading.Thread(target=_send_online, args=(entry,), daemon=True).start()


def read_feedback() -> list:
    """קורא את כל ההודעות המקומיות (לשימוש המפתח). מתעלם משורות פגומות."""
    out = []
    if not os.path.exists(FEEDBACK_PATH):
        return out
    with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
    return out
