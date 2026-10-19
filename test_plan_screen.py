# -*- coding: utf-8 -*-
"""הכנה קדימה — שלב 2, נעילת רשימות: המסך (offscreen, DB זמני, "היום" מזויף).

S0 — בידוד התחזית מההגדרות של השבוע האמיתי (U3) ופלטים שנכשלים סגור (U8):
  • בתחזית "מוצרים זמינים"/"רזרבה" נשמרים בזיכרון בלבד — לא נכתבים ל-available_products /
    reserve_count / weekly_extra_ids; תחזית חדשה מתחילה מהמספרים של השבוע האמיתי
  • "חלוקה חדשה" בתחזית לא נוגעת בכלום
  • week_rows() ריק בתחזית (צינתוק ומייל לא מגיעים לשבוע אחר)
הרצה: python test_plan_screen.py  (Python 3.12)"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
import database as db
_d = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_d, "data.db"); db.BACKUP_DIR = os.path.join(_d, "backups"); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox
shown = []
for _m in ("information", "critical", "warning"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: shown.append(" ".join(str(x) for x in a[1:3]))))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

import datetime as _dtm
import selection
import tabs.group_update as gu
_Real = _dtm.date
class _Fake(_Real):
    _today = _Real(2026, 10, 18)                      # יום ראשון; הרביעי הקרוב = 21/10
    @classmethod
    def today(cls):
        t = cls._today
        return _Real(t.year, t.month, t.day)
db.date = _Fake; selection._date = _Fake; gu.date = _Fake
D = _Real
SUN, W1, W2, W3 = D(2026, 10, 18), D(2026, 10, 21), D(2026, 10, 28), D(2026, 11, 4)

db.set_setting("dist_regulars_mode", "schedule")
db.set_setting("available_products", "50"); db.set_setting("reserve_count", "3")
db.set_setting("weekly_extra_ids", ""); db.set_setting("weekly_reserve_ids", "")
for i in range(6):
    db.add_recipient({"full_name": f"שבועי {i}", "status": "פעיל", "frequency": "שבועי", "priority": 4,
                      "souls": 3, "children_total": 3})

from main import MainWindow
win = MainWindow()
gt, tz, ml = win.group_tab, win.tzintukim_tab, win.mails_tab

def set_date(d):
    gt.date_edit.set_from_iso(d.isoformat())

def settings():
    return {k: db.get_setting(k) for k in ("available_products", "reserve_count",
                                            "weekly_extra_ids", "weekly_reserve_ids")}

set_date(SUN); gt.refresh(); gt._needs_refresh = False
real0 = settings()
ok("U3a השבוע האמיתי: הספינרים = ההגדרות המשותפות", (gt.products_spin.value(), gt.reserve_spin.value()) == (50, 3))

# ── U3 — תחזית לא כותבת להגדרות של השבוע האמיתי ───────────────────────────────────
set_date(W2)
ok("U3b תחזית חדשה מתחילה מהמספרים של השבוע האמיתי (הצעה גלויה)",
   gt.list_is_future() and (gt.products_spin.value(), gt.reserve_spin.value()) == (50, 3))
gt.products_spin.setValue(4); gt.reserve_spin.setValue(1)
ok("U3c שינוי מוצרים/רזרבה בתחזית לא כותב ל-available_products / reserve_count / הבחירות", settings() == real0, str(settings()))
ok("U3d הרשימה בתחזית עוקבת אחרי המספרים שבזיכרון (4 + רזרבה 1 = 5 שורות)", len(gt._rows_data) == 5, str(len(gt._rows_data)))
set_date(W3)
ok("U3e תחזית של שבוע אחר מתחילה מחדש מהשבוע האמיתי (50/3) — לא מדליפה מהתחזית הקודמת",
   (gt.products_spin.value(), gt.reserve_spin.value()) == (50, 3))
set_date(W2)
ok("U3f חזרה לאותה תחזית: הערכים שלה נשמרו בזיכרון (4/1)",
   (gt.products_spin.value(), gt.reserve_spin.value()) == (4, 1))
set_date(SUN)
ok("U3g חזרה לשבוע האמיתי: הערכים האמיתיים כפי שהיו, וההגדרות לא נגעו",
   (gt.products_spin.value(), gt.reserve_spin.value()) == (50, 3) and settings() == real0)
gt.products_spin.setValue(40)
ok("U3h בשבוע האמיתי שינוי כן נכתב להגדרות (כמו תמיד)", db.get_setting("available_products") == "40")
gt.products_spin.setValue(50)
real0 = settings()

# מצב סינון: החיתוך ב-DB משתמש במספרים של התחזית, לא בהגדרות
set_date(W2)
db.set_setting("dist_regulars_mode", "filter")      # דרך ההגדרה — בחירה בקומבו פותחת דיאלוג סינון
db.set_filter_criteria({"balance_communities": False})
gt.products_spin.setValue(2); gt.reserve_spin.setValue(0)
gt.refresh()
ok("U3i 'סינון מותאם' בתחזית נחתך למספר המוצרים של התחזית (2), וההגדרות לא נגעו",
   len(gt._rows_data) == 2 and settings() == real0, f"{len(gt._rows_data)} / {settings()}")
db.set_setting("dist_regulars_mode", "schedule"); gt.refresh()

# "חלוקה חדשה" בתחזית לא נוגעת בכלום
shown.clear()
gt._reset_for_new()
ok("U3j 'חלוקה חדשה' בתחזית נחסמת בהסבר ולא מאפסת את השבוע האמיתי", settings() == real0 and len(shown) == 1, str(shown))

# ── U8 — פלטים נכשלים סגור ───────────────────────────────────────────────────────
ok("U8a week_rows() בתחזית ריק", gt.list_is_future() and gt.week_rows() == [])
set_date(SUN)
gt.refresh()
ok("U8b week_rows() בשבוע הנוכחי רגיל (בלי רזרבות)", len(gt.week_rows()) >= 1
   and all(not r.get("_reserve") for r in gt.week_rows()))

print()
print("RESULT:", "ALL PLAN-SCREEN CHECKS PASS ✓" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
