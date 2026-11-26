"""Launcher for a stand-alone copy of the website (the zip for the fund manager's computer).

Double-click -> on the first run, takes a byte copy of the desktop program's data.db
(only read, nothing is written next to it) and imports it; then starts the site on
127.0.0.1:8787 and opens the browser.  "--reimport" rebuilds from a fresh copy.
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import webbrowser

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "HalukaWebCopy")
os.environ.setdefault("HALUKA_WEB_DATA", DATA_DIR)

if getattr(sys, "frozen", False):
    sys.path.insert(0, sys._MEIPASS)  # noqa

from web import config, import_old  # noqa: E402


def _old_db() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), "ManhalHaluka", "data.db")


def _import(replace: bool) -> None:
    src = _old_db()
    if not os.path.exists(src):
        print("לא נמצאו נתונים של התוכנה הישנה:", src)
        input("Enter לסגירה")
        sys.exit(1)
    with tempfile.TemporaryDirectory() as tmp:
        cp = os.path.join(tmp, "data.db")
        shutil.copyfile(src, cp)
        if os.path.exists(src + "-wal"):
            shutil.copyfile(src + "-wal", cp + "-wal")
        rep = import_old.import_old(cp, os.path.join(DATA_DIR, "haluka.db"), replace=replace)
    print("הייבוא הסתיים:", rep)


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    db = os.path.join(DATA_DIR, "haluka.db")
    if "--reimport" in sys.argv or not os.path.exists(db):
        print("מעתיק את הנתונים מהתוכנה הישנה (רק קריאה)...")
        _import(replace=os.path.exists(db))
    import uvicorn
    from web.app import app
    threading.Thread(target=lambda: (time.sleep(2), webbrowser.open("http://127.0.0.1:8787")),
                     daemon=True).start()
    print("האתר פועל: http://127.0.0.1:8787  —  לסגירה: לסגור את החלון הזה")
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="warning")


if __name__ == "__main__":
    main()
