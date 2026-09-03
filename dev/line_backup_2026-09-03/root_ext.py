"""כלי שחזור/החלה של ext.ini בשורש הקו (3/9/2026 — תיקון "חוזר לצינתוק לא שומע").

    python dev/line_backup_2026-09-03/root_ext.py show      # מה יש עכשיו בקו
    python dev/line_backup_2026-09-03/root_ext.py apply     # כותב את root_ext.ini.new
    python dev/line_backup_2026-09-03/root_ext.py restore   # מחזיר את root_ext.ini.orig

הכתיבה דרך UploadTextFile של התוכנה (אותו מסלול כמו שלוחה 77). לפני כל כתיבה
נשמר עותק של המצב הנוכחי בקו ל-root_ext.ini.before-<זמן>.
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from utils import yemot

WHAT = "ivr2:/ext.ini"


def current() -> str:
    return yemot._download(WHAT).decode("utf-8", errors="replace")


def write(text: str) -> None:
    snap = os.path.join(HERE, f"root_ext.ini.before-{time.strftime('%Y%m%d-%H%M%S')}")
    with open(snap, "w", encoding="utf-8") as f:
        f.write(current())
    yemot._call("UploadTextFile", {"what": WHAT, "contents": text}, post=True)
    after = current()
    print("נכתב." if after.strip() == text.strip() else "⚠ הקובץ בקו שונה מהצפוי:\n" + after)


if __name__ == "__main__":
    mode = (sys.argv[1:] or ["show"])[0]
    if mode == "show":
        print(current())
    elif mode in ("apply", "restore"):
        name = "root_ext.ini.new" if mode == "apply" else "root_ext.ini.orig"
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            write(f.read())
    else:
        print(__doc__)
