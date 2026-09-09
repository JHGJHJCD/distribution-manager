# -*- coding: utf-8 -*-
"""בודק-תקינות של שרת המענה — קריאה בלבד, לא כותב שום דבר.

הרצה:
    <py312> .claude/skills/tzintuk-callback-server/scripts/check_callback.py [--backup]

מראה בפקודה אחת איפה עומד החיבור: Worker, /76, 2 שורות השורש, המתג — ומה תקין.
`--backup` שומר גיבוי טרי של שני קבצי השורש ל-dev/line_change_2026-09-10_callback_route/.
יציאה 0 = נקרא בהצלחה (גם אם יש צעדים שעוד לא בוצעו); != 0 = תקלת קריאה/רשת.
"""
import io
import os
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OK, BAD, WARN = "🟢", "🔴", "🟡"


def _line(mark, label, detail=""):
    print(f"  {mark}  {label}" + (f"  — {detail}" if detail else ""))


def main():
    do_backup = "--backup" in sys.argv
    import database as db
    from utils import yemot
    from utils import callback_server as cb

    print("=== בודק שרת המענה (קריאה בלבד) ===")
    rc = 0

    # 1. Worker + D1 reachable
    try:
        n = cb.check_connection()
        _line(OK, "Worker בענן עונה", f"{cb.base_url()} · {n} תשובות במסד")
    except Exception as e:
        _line(BAD, "Worker לא נגיש", str(e)[:120])
        rc = 1

    # 2. /76 extension
    try:
        problem = cb.verify_extension()
        if problem:
            _line(BAD, "שלוחה /76", problem.replace("\n", " ")[:140])
        else:
            _line(OK, "שלוחה /76 תקינה", "type=api + כתובת + music_off + end_goto=/")
    except Exception as e:
        _line(WARN, "בדיקת /76 נכשלה", str(e)[:120])

    # 3 + 4. root lines (read-only download)
    root = didgo = ""
    try:
        root = yemot._download("ivr2:/ext.ini").decode("utf-8", "replace")
    except Exception as e:
        _line(WARN, "קריאת שורש ext.ini נכשלה", str(e)[:120])
    try:
        didgo = yemot._download("ivr2:/Did_Go_To.ini").decode("utf-8", "replace")
    except Exception as e:
        _line(WARN, "קריאת Did_Go_To.ini נכשלה", str(e)[:120])

    guard = "check_did_and_go_to_folder_one_time=yes"
    route = "048691834=/76"
    step1 = guard in root
    step2 = route in didgo
    _line(OK if step1 else BAD, "שורש: מונע-לולאה (צעד 1)",
          "קיים" if step1 else "חסר — להוסיף " + guard)
    _line(OK if step2 else BAD, "Did_Go_To: ניתוב /76 (צעד 2)",
          "קיים" if step2 else "חסר — להוסיף " + route)
    if root and "campaign_message_to_play" in root:
        camp = [l for l in root.splitlines() if l.startswith("campaign_message_to_play")]
        _line(OK, "שורת הברכה של רון", camp[0] if camp else "?")

    # 5. software switch
    enabled = db.get_setting("cb_server_enabled") == "1"
    sec = (db.get_setting("cb_server_secret") or "").strip()
    url = (db.get_setting("cb_server_url") or "").strip()
    _line(OK if enabled else BAD, "מתג cb_server_enabled (צעד 3)",
          "דלוק" if enabled else "כבוי")
    _line(OK if sec else BAD, "סוד שמור", f"{len(sec)} תווים" if sec else "חסר")
    _line(OK, "כתובת", url or f"(ריק → נופל ל-DEFAULT_URL: {cb.DEFAULT_URL})")

    # 6. line health (default OPEN, units) — best effort
    try:
        s = yemot._call("GetSession", {})
        units = s.get("units")
        _line(OK, "הקו עונה", f"יתרה ~{units}" if units is not None else "GetSession תקין")
    except Exception as e:
        _line(WARN, "GetSession נכשל", str(e)[:120])

    # backup
    if do_backup and root and didgo:
        d = os.path.join(ROOT, "dev", "line_change_2026-09-10_callback_route")
        os.makedirs(d, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for name, content in (("ext", root), ("Did_Go_To", didgo)):
            p = os.path.join(d, f"{name}.before-{stamp}.ini")
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            print("  גיבוי:", p)

    done = sum([step1, step2, enabled])
    print(f"\n=== סיכום: {done}/3 צעדי החיבור בוצעו ===")
    if done < 3:
        print("    נותר: " + ", ".join(
            [t for t, ok in (("מונע-לולאה בשורש", step1),
                             ("ניתוב Did_Go_To", step2),
                             ("הדלקת המתג", enabled)) if not ok]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
