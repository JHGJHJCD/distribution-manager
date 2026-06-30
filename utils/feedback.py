"""ערוץ הודעות מהמשתמש למפתח.

המשתמש יכול להשאיר הודעה על תקלה / בקשה דרך כפתור קטן בשורת המצב. ההודעות
נשמרות כקובץ JSONL ב-%APPDATA%\\ManhalHaluka\\feedback.jsonl — הקובץ אינו מוצג
בשום מסך בתוכנה; הוא נועד לקריאה ע"י המפתח (Claude) בלבד בעת תחזוקת הקוד.

כל שורה היא רשומת JSON עצמאית, כך שכתיבה נכשלת לעולם לא תפגע ברשומות קודמות.
"""
import os
import json
from datetime import datetime

import database as db

try:
    from version import APP_VERSION
except Exception:
    APP_VERSION = "?"

FEEDBACK_PATH = os.path.join(db._data_dir(), "feedback.jsonl")


def save_feedback(message: str, name: str = "") -> None:
    """מצרף הודעת משתמש לקובץ ההודעות (append-only, UTF-8)."""
    message = (message or "").strip()
    if not message:
        return
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": (name or "").strip(),
        "version": APP_VERSION,
        "os": f"{os.name}",
        "host": os.environ.get("COMPUTERNAME", ""),
        "message": message,
    }
    line = json.dumps(entry, ensure_ascii=False)
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_feedback() -> list:
    """קורא את כל ההודעות (לשימוש המפתח). מתעלם משורות פגומות."""
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
