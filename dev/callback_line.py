"""כלי בנייה/בדיקה/שחזור של "הודעת החלוקה בהתקשרות חוזרת" בקו (3/9/2026, גרסה 3.06).

    python dev/callback_line.py show      # מצב נוכחי: שורש + שלוחה 78 + הרשימה בתבנית
    python dev/callback_line.py apply     # בונה/מתקן: פילטר בשורש, שלוחה 78, קישורים, קובץ ההודעה
    python dev/callback_line.py restore   # מחזיר את השורש למצב שלפני (root_ext.ini.orig) ומוחק את שלוחה 78

המנגנון (utils/yemot.py, ensure_callback_extension): מי שמספרו ברשימת התבנית של
התוכנה ומחייג לקו מופנה מהשלוחה הראשית ל-/78 (check_template_filter), שומע את
הודעת הצינתוק ואז את התפריט הרגיל (קישורי-מקשים חזרה לשלוחות הראשיות). כל שאר
המתקשרים נכנסים לתפריט הראשי כרגיל. לפני כל כתיבה לשורש נשמר עותק ב-
%APPDATA%/ManhalHaluka/line_backups/ ובתיקיית הגיבוי כאן.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from utils import yemot                                    # noqa: E402

BACKUP = os.path.join(HERE, "line_backup_2026-09-03-callback")
ORIG = os.path.join(BACKUP, "root_ext.ini.orig")


def snapshot(tag: str) -> str:
    os.makedirs(BACKUP, exist_ok=True)
    text = yemot._read_text(yemot.ROOT_EXT_INI) or ""
    path = os.path.join(BACKUP, f"root_ext.ini.{tag}-{time.strftime('%Y%m%d-%H%M%S')}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if not os.path.exists(ORIG):
        with open(ORIG, "w", encoding="utf-8") as f:
            f.write(text)
    return path


def show() -> None:
    tid = yemot.ensure_template()
    pos = yemot.template_position(tid)
    print(f"תבנית התוכנה: {tid} — מיקום {pos} ברשימת התבניות")
    print("── שורש ext.ini ──")
    print(yemot._read_text(yemot.ROOT_EXT_INI))
    print(f"── שלוחה {yemot.CALLBACK_EXT} ──")
    try:
        d = yemot._call("GetIVR2Dir", {"path": f"ivr2:/{yemot.CALLBACK_EXT}"})
        print("ext.ini:", yemot._read_text(f"ivr2:/{yemot.CALLBACK_EXT}/ext.ini"))
        print("קישורים:", sorted(x["name"] for x in d.get("dirs") or [] if x.get("exists")))
        print("קבצים:", [f["name"] for f in d.get("files") or []])
    except yemot.YemotError as e:
        print("לא קיימת:", e)
    entries = yemot._call("GetTemplateEntries", {"templateId": tid})
    print("ברשימת התבנית:", [e.get("phone") for e in entries.get("entries") or []])


def apply() -> None:
    print("גיבוי השורש:", snapshot("before-apply"))
    res = yemot.ensure_callback_extension()
    print("תוצאה:", res)
    print("קובץ ההודעה:", yemot.publish_callback_message())
    print("גיבוי אחרי:", snapshot("after-apply"))


def restore() -> None:
    print("גיבוי לפני שחזור:", snapshot("before-restore"))
    with open(ORIG, encoding="utf-8") as f:
        orig = f.read()
    yemot._write_text(yemot.ROOT_EXT_INI, orig)
    now = yemot._read_text(yemot.ROOT_EXT_INI) or ""
    print("השורש שוחזר." if now.strip() == orig.strip() else "⚠ השורש שונה מהצפוי:\n" + now)
    try:
        yemot._call("FileAction", {"what": f"ivr2:/{yemot.CALLBACK_EXT}",
                                   "action": "delete"}, post=True)
        print(f"שלוחה {yemot.CALLBACK_EXT} נמחקה (לסל של ימות).")
    except yemot.YemotError as e:
        print(f"מחיקת שלוחה {yemot.CALLBACK_EXT} נכשלה — למחוק בממשק ימות:", e)
    import database as db
    db.set_setting(yemot.SET_CALLBACK_READY, "")


if __name__ == "__main__":
    mode = (sys.argv[1:] or ["show"])[0]
    {"show": show, "apply": apply, "restore": restore}.get(mode, lambda: print(__doc__))()
