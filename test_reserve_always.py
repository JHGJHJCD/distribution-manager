# -*- coding: utf-8 -*-
"""RULE 3 — הרזרבה מופיעה כל פעם (יהודה 21/10/2026: "המנהל חלוקה לא רושם רזרבות במצבים
השונים וגם לא במצב נעילה"). הבאג: החיתוכים (limit_due_regulars / limit_to_products /
assign_roles) יוצרים רזרבה רק כשיש יותר מועמדים ממוצרים; בקבוצה שבועית קטנה כולם נכנסים
והרזרבה יצאה ריקה — בכל המצבים, ולכן גם בנעילה (שמורה את מה שהמסך מציג).

  U — selection.top_up_reserve (טהור)
  S — המסך בכל המצבים: schedule / scored / filter / none
  L — נעילה: הרזרבה נשמרת, נטענת, לא נרשמת אוטומטית, לא תופסת, ועלייה בכמות ממלאת
  F — תחזית (הכנה קדימה) ונעילת תחזית
הרצה: python test_reserve_always.py  (Python 3.12)"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
from datetime import date, timedelta
import database as db
import selection
_d = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_d, "data.db"); db.BACKUP_DIR = os.path.join(_d, "backups"); db.init_db()

from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

# ═══ U — הפונקציה הטהורה ═══════════════════════════════════════════════════════════
def mk(i, **kw):
    return dict({"id": i, "full_name": f"p{i}"}, **kw)
mains = [mk(i, _role="main", _reserve=False) for i in range(1, 4)]
queue = [mk(i) for i in range(10, 20)]

out = selection.top_up_reserve(mains, 2, 3, queue)
ok("U1 מוצרים = ברשימה, רזרבה 2 → 2 מהתור נוספים, מסומנים, בסוף",
   [r["id"] for r in out] == [1, 2, 3, 10, 11] and all(r["_reserve"] and r["_topup"] and r["_role"] == "reserve" for r in out[3:]),
   str([r["id"] for r in out]))
ok("U1b הרשימה שהועברה לא שונתה", [r["id"] for r in mains] == [1, 2, 3])

queue = [mk(i) for i in range(10, 20)]
out = selection.top_up_reserve(mains, 2, 8, queue)
ok("U2 נשארו 5 מוצרים לחד-פעמיים → הרזרבה היא אחרי 5 הראשונים בתור (11..): 15,16",
   [r["id"] for r in out[3:]] == [15, 16], str([r["id"] for r in out]))

queue = [mk(i) for i in range(10, 13)]
out = selection.top_up_reserve(mains, 2, 8, queue)
ok("U3 תור קצר מדי → עדיין רזרבה (לא ריק)", len([r for r in out if r.get("_reserve")]) == 2,
   str([r["id"] for r in out]))

queue = [mk(i) for i in range(10, 20)]
withres = mains + [mk(50, _role="reserve", _reserve=True)]
out = selection.top_up_reserve(withres, 2, 3, queue)
ok("U4 רזרבה קיימת (בחירה ידנית/מחיתוך) נספרת: חסרה רק אחת", [r["id"] for r in out[4:]] == [10], str([r["id"] for r in out]))
ok("U4b רזרבה מלאה → בלי שינוי", len(selection.top_up_reserve(withres, 1, 3, queue)) == 4)
ok("U5 מוצרים 0 / רזרבה 0 → בלי שינוי",
   len(selection.top_up_reserve(mains, 2, 0, queue)) == 3 and len(selection.top_up_reserve(mains, 0, 5, queue)) == 3)
out = selection.top_up_reserve(mains, 2, 3, [mk(1)] + [mk(i) for i in range(10, 14)], exclude_ids={10})
ok("U6 מי שכבר ברשימה או הוסר ב-🗑 לא חוזר כרזרבה", [r["id"] for r in out[3:]] == [11, 12], str([r["id"] for r in out]))

# ═══ נתונים ════════════════════════════════════════════════════════════════════════
today = date.today()
REG = [db.add_recipient({
    "full_name": f"קבוע {i}", "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 3,
    "children_total": 3, "representative": "א" if i % 2 else "ב",
    "last_distribution": (today - timedelta(days=14 + 7 * i)).isoformat()}) for i in range(5)]
NOT_DUE = db.add_recipient({"full_name": "חודשי לא בתור", "status": "פעיל", "frequency": "חודשי",
                            "priority": 4, "souls": 2, "children_total": 2,
                            "last_distribution": (today - timedelta(days=7)).isoformat()})
ONE = [db.add_recipient({"full_name": f"חדפ {i}", "status": "פעיל", "frequency": "חד-פעמי",
                         "priority": 3, "souls": 4 + i}) for i in range(8)]

from main import MainWindow
win = MainWindow()
gt = win.group_tab
import tabs.group_update as gu
gu.OneTimePickerDialog.exec = lambda self: QDialog.DialogCode.Accepted

def set_mode(mode):
    db.set_setting("dist_regulars_mode", mode)       # (הקומבו בפילטר פותח דיאלוג) — refresh מסנכרן את הקומבו
    gt.refresh()

def rows():
    return [(r["id"], bool(r.get("_reserve") or r["id"] in gt._reserve_ids)) for r in gt._rows_data]
def mains_(): return [i for i, res in rows() if not res]
def res_(): return [i for i, res in rows() if res]

db.set_filter_criteria({"children_total": {"min": 1, "max": None}, "balance_communities": False})

# ═══ S — כל המצבים, מוצרים מספיקים לכולם ═══════════════════════════════════════════
for mode in ("schedule", "scored", "filter", "none"):
    set_mode(mode)
    gt.reserve_spin.setValue(2); gt.products_spin.setValue(25)
    if mode == "none":
        ok("S0 none: בלי אף אחד ברשימה → טבלה ריקה, גם עם רזרבה (כמו תמיד)", rows() == [], str(rows()))
        gt.add_one_time_picks([{"id": REG[0], "_reserve": False}])      # (נשאר עד סוף הלולאה)
    ok(f"S1 {mode}: מוצרים מספיקים לכולם + רזרבה 2 → 2 רזרבות מופיעות", len(res_()) == 2, str(rows()))
    ok(f"S1b {mode}: הרזרבה מהתור של החד-פעמיים, לא קבוע שתורו לא הגיע",
       set(res_()) <= set(ONE) and NOT_DUE not in res_(), str(res_()))
    ok(f"S1c {mode}: צינתוקים/מיילים לא מקבלים רזרבות", not any(r["id"] in res_() for r in gt.week_rows()))
    gt.reserve_spin.setValue(0)
    ok(f"S2 {mode}: רזרבה 0 → אין", res_() == [], str(res_()))
    gt.reserve_spin.setValue(3)
    ok(f"S3 {mode}: רזרבה 3 → 3", len(res_()) == 3, str(res_()))
    gt.products_spin.setValue(0)
    ok(f"S4 {mode}: מוצרים 0 → טבלה ריקה (כמו תמיד)", rows() == [], str(rows()))
    if mode == "none":
        gt._extra_ids.clear(); gt._reserve_ids.clear(); gt._persist_extras()

set_mode("schedule")
gt.reserve_spin.setValue(2); gt.products_spin.setValue(25)
ok("S5 'בחר הכל' לא מסמן רזרבה", (gt._check_all(), not (set(gt._checked_ids) & set(res_())))[1])
gt._uncheck_all()
first = res_()
gt.add_one_time_picks([{"id": first[0], "_reserve": False}])
ok("S6 הרזרבה שנבחרה ידנית כעיקרית עוברת לעיקריים, והבא בתור נכנס לרזרבה",
   first[0] in mains_() and len(res_()) == 2 and first[0] not in res_(), f"{mains_()} / {res_()}")
gt._extra_ids.clear(); gt._reserve_ids.clear(); gt._persist_extras()

# 🗑 על רזרבה — לא חוזרת
gt.refresh()
victim = res_()[0]
gt._remove_from_list({"id": victim})
ok("S7 מי שהוסר ב-🗑 לא חוזר כרזרבה", victim not in [i for i, _ in rows()] and len(res_()) == 2, str(rows()))
gt._removed_ids.clear(); gt.refresh()

# ═══ L — נעילה ═════════════════════════════════════════════════════════════════════
set_mode("schedule")
gt.reserve_spin.setValue(2); gt.products_spin.setValue(25)
before = res_()
gt._lock_plan()
plan = gt._plan
ok("L1 נעילה כשהכול נכנס למוצרים: 2 רזרבות נשמרות כחברות 'reserve'",
   plan is not None and [m["role"] for m in plan["members"]].count("reserve") == 2,
   str([m["role"] for m in plan["members"]] if plan else None))
ok("L1b אותם אנשים שהוצגו לפני הנעילה", set(res_()) == set(before), f"{res_()} vs {before}")
saved = db.get_plan(gt._plan_week())
ok("L2 הרזרבות שמורות במסד", [m["role"] for m in saved["members"]].count("reserve") == 2)
gt.refresh()
ok("L3 טעינה מחדש של המסך הנעול מציגה את אותן רזרבות", len(res_()) == 2 and set(res_()) == set(before), str(res_()))
ok("L3b נעול: צינתוקים/מיילים בלי רזרבות", not any(r["id"] in res_() for r in gt.week_rows()))
idx = db.live_plan_index() if hasattr(db, "live_plan_index") else {}
res_guids = {m["g"] for m in saved["members"] if m["role"] == "reserve"}
ok("L4 רזרבה בנעילה לא תופסת אף אחד לשבועות אחרים", not (res_guids & set(idx)), str(idx))
import sqlite3
with db.get_connection() as _c:
    recs, info = db._autoreg_members(_c, saved)
ok("L5 רישום אוטומטי (כלל 11) מדלג על הרזרבה בכוונה", info["reserve"] == 2 and
   not ({r["guid"] for r in recs} & res_guids), str(info))

# עלייה בכמות הרזרבה בנעילה ממלאת; ירידה לא מסירה
gt.reserve_spin.setValue(3)
saved = db.get_plan(gt._plan_week())
ok("L6 הגדלת הרזרבה ברשימה נעולה מצרפת את החסר", [m["role"] for m in saved["members"]].count("reserve") == 3
   and len(res_()) == 3, str([m["role"] for m in saved["members"]]))
gt.reserve_spin.setValue(1)
saved = db.get_plan(gt._plan_week())
ok("L6b הקטנה לא מסירה אף אחד (הרשימה הנעולה קפואה; 🗑 מסיר)",
   [m["role"] for m in saved["members"]].count("reserve") == 3)
gt._unlock_plan()
ok("L7 ביטול נעילה: חוזרים לרשימה חיה עם רזרבה", gt._plan is None)

# ═══ F — תחזית ═════════════════════════════════════════════════════════════════════
nxt = selection.upcoming_wednesday() + timedelta(days=7)
gt.date_edit.set_from_iso(nxt.isoformat())
ok("F0 המסך במצב תחזית", gt.list_is_future())
gt.products_spin.setValue(8); gt.reserve_spin.setValue(2)       # 5 קבועים + 3 חד-פעמיים מוצעים + רזרבה
ok("F1 תחזית עם מוצרים מספיקים: 2 רזרבות מופיעות", len(res_()) == 2, str(rows()))
ok("F1b בתחזית צינתוקים/מיילים ריקים (נכשל סגור)", gt.week_rows() == [])
gt._lock_plan()
saved = db.get_plan(selection.upcoming_wednesday(nxt))
roles = [m["role"] for m in saved["members"]] if saved else []
ok("F2 נעילת תחזית: 3 חד-פעמיים מוצעים כעיקריים + 2 רזרבות (ההצעה והרזרבה לא מתנגשות)",
   roles.count("reserve") == 2 and roles.count("main") == 8, str(roles))
ok("F2b הרזרבה היא הבאים אחרי ה-3 שהוצעו, לא מי שהוצע", not ({m["g"] for m in saved["members"] if m["role"] == "reserve"}
   & {m["g"] for m in saved["members"] if m["role"] == "main"}))
gt.refresh()
ok("F3 התחזית הנעולה מציגה אותן", len(res_()) == 2, str(res_()))
ok("F4 ההגדרות של השבוע האמיתי לא נגעו", db.get_setting("reserve_count") != "" and True)

print("\nRESULT:", "ALL RESERVE TESTS PASS ✓" if not fails else f"FAILURES: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)
