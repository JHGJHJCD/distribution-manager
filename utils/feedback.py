"""ערוץ הודעות מהמשתמש למפתח.

המשתמש יכול להשאיר הודעה על תקלה / בקשה דרך כפתור קטן בשורת המצב.

שני יעדים, משלימים:
1. שמירה מקומית תמיד — קובץ JSONL ב-%APPDATA%\\ManhalHaluka\\feedback.jsonl
   (גיבוי שלא הולך לאיבוד גם אם אין רשת).
2. שליחה לגיטאב כ-Issue — אם הוטמע טוקן (ראה _secret.py). כך גם הודעות
   ממחשבי מתנדבים אחרים מגיעות למפתח. השליחה רצה ב-thread ברקע כדי לא לתקוע
   את הממשק, ואם היא נכשלת (אין רשת / אין טוקן) — נשארת השמירה המקומית.

הטוקן והריפו לא נשמרים בקוד המקור הציבורי; הם מגיעים מ-_secret.py שאינו
נכנס ל-git ומוטמע רק ב-EXE הבנוי.
"""
import os
import json
import threading
from datetime import datetime

import database as db

try:
    from version import APP_VERSION
except Exception:
    APP_VERSION = "?"

# Embedded GitHub config — present only in the built EXE (not in the public repo).
try:
    from _secret import GH_FEEDBACK_TOKEN, GH_FEEDBACK_REPO  # type: ignore
except Exception:
    GH_FEEDBACK_TOKEN = None
    GH_FEEDBACK_REPO = None

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


def _post_github(entry: dict) -> bool:
    """Create a GitHub issue for this feedback. Returns True on success.
    Best-effort: any failure is swallowed (the local copy is the safety net)."""
    if not (GH_FEEDBACK_TOKEN and GH_FEEDBACK_REPO):
        return False
    import urllib.request
    title = f"משוב v{entry['version']}"
    if entry["name"]:
        title += f" — {entry['name']}"
    body = (
        f"{entry['message']}\n\n"
        f"---\n"
        f"זמן: {entry['ts']}\n"
        f"שם: {entry['name'] or '—'}\n"
        f"גרסה: {entry['version']}\n"
        f"מחשב: {entry['host'] or '—'}"
    )
    data = json.dumps({"title": title, "body": body,
                       "labels": ["feedback"]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GH_FEEDBACK_REPO}/issues",
        data=data, method="POST",
        headers={
            "Authorization": f"Bearer {GH_FEEDBACK_TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ManhalHaluka-Feedback",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def save_feedback(message: str, name: str = "") -> None:
    """שומר את ההודעה מקומית (סינכרוני) ושולח לגיטאב ברקע אם מוגדר טוקן."""
    message = (message or "").strip()
    if not message:
        return
    entry = _entry(message, name)
    _save_local(entry)        # always — never lose a message
    if GH_FEEDBACK_TOKEN and GH_FEEDBACK_REPO:
        threading.Thread(target=_post_github, args=(entry,), daemon=True).start()


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
