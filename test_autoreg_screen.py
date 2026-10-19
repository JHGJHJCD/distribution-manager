# -*- coding: utf-8 -*-
"""כלל 11 — רישום אוטומטי של רשימה נעולה: המסך (offscreen, DB זמני, "היום" מזויף).

מוכיח:
  • באנר הנעילה נושא את מתג הרישום האוטומטי (ברירת מחדל דלוק), והמתג נכתב בלי לגעת בנעילה
  • הטיימר מחובר, ו-autoreg_tick רושם בזמן הנכון בלבד, בלי חלון קופץ
  • אחרי רישום: הבאנר "נרשם אוטומטית" גלוי, status_msg, מצב הנעילה ננטש, הבחירות של מי שנרשם הוסרו
  • "הכול נכון" מסתיר את הבאנר; "חלוקות קודמות" מסמנת את האצווה; "תכנונים" מציג את המצב
  • week_rows (צינתוק/מייל) לא מושפע
הרצה: python test_autoreg_screen.py  (Python 3.12)"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
import database as db
_d = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_d, "data.db"); db.BACKUP_DIR = os.path.join(_d, "backups"); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox
shown = []
for _m in ("information", "critical", "warning", "question"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: (shown.append(" ".join(str(x) for x in a[1:3])),
                                                           QMessageBox.StandardButton.Yes)[1]))
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

import datetime as _dtm
from datetime import datetime
import selection
import tabs.group_update as gu
import tabs.plan_lock as pl
_Real = _dtm.date
class _Fake(_Real):
    _today = _Real(2026, 10, 18)
    @classmethod
    def today(cls):
        t = cls._today
        return _Real(t.year, t.month, t.day)
db.date = _Fake; selection._date = _Fake; gu.date = _Fake; pl.date = _Fake
D = _Real
SUN, W1, THU = D(2026, 10, 18), D(2026, 10, 21), D(2026, 10, 22)
THU_0559, THU_0600 = datetime(2026, 10, 22, 5, 59), datetime(2026, 10, 22, 6, 0)

db.set_setting("dist_regulars_mode", "schedule")
db.set_setting("available_products", "50"); db.set_setting("reserve_count", "2")
db.set_setting("weekly_extra_ids", ""); db.set_setting("weekly_reserve_ids", "")
WK = [db.add_recipient({"full_name": f"ש-{i}", "status": "פעיל", "frequency": "שבועי", "priority": 4,
                        "souls": 3, "children_total": 3}) for i in range(5)]
R_M = db.add_recipient({"full_name": "חודשי-ב", "status": "פעיל", "frequency": "חודשי", "priority": 4, "souls": 3})
def guid(rid): return db.get_recipient(rid)["guid"]

from main import MainWindow
win = MainWindow()
gt = win.group_tab

# ── הטיימר מחובר ─────────────────────────────────────────────────────────────────
ok("S1a הטיימר של הרישום האוטומטי פעיל, כל 5 דקות", gt._autoreg_timer.isActive() and gt._autoreg_timer.interval() == 300000)

# ── מתג בבאנר ────────────────────────────────────────────────────────────────────
gt.date_edit.set_from_iso(SUN.isoformat()); gt._set_stage("prep", clear=False); gt.refresh()
gt.dist_input.setCurrentText("רון")
gt._lock_plan()
plan = db.get_plan(W1)
ok("S2a נעילה נוצרה, מחלק נשמר בה", plan is not None and plan.get("distributor") == "רון")
ok("S2b המתג בבאנר גלוי ודלוק, והטקסט מציין חמישי 22/10 ב-06:00",
   gt._plan_mode() and gt.chk_plan_autoreg.isVisibleTo(gt) and gt.chk_plan_autoreg.isChecked()
   and "22/10" in gt.chk_plan_autoreg.text() and "06:00" in gt.chk_plan_autoreg.text(), gt.chk_plan_autoreg.text())
ok("S2c אין באנר 'נרשם אוטומטית' לפני הרישום", not gt.autoreg_banner_frame.isVisibleTo(gt))
stamp = db.get_plan(W1)["updated_at"]
gt.chk_plan_autoreg.setChecked(False)
ok("S2d כיבוי המתג נכתב (המפתח הנפרד) בלי להזיז את updated_at של הנעילה",
   db.get_autoreg(db.get_plan(W1))["enabled"] is False and db.get_plan(W1)["updated_at"] == stamp)
ok("S2e אחרי רענון המסך המתג נשאר כבוי", (gt.refresh(), not gt.chk_plan_autoreg.isChecked())[1])
ok("S2f כבוי ← autoreg_tick בחמישי 06:00 לא רושם", gt.autoreg_tick(THU_0600) == [] and not db.get_distribution_batches())
gt.chk_plan_autoreg.setChecked(True)
ok("S2g דלוק שוב", db.get_autoreg(db.get_plan(W1))["enabled"])

# ── הטיימר: לא לפני הזמן, כן בזמן ──────────────────────────────────────────────────
db.set_setting("weekly_extra_ids", guid(WK[0]) + "," + guid(R_M))     # בחירות שבוע: שניים מהנעילה
gt.refresh()
rows_before = {r["id"] for r in gt._rows_data if not r.get("_reserve")}
shown.clear()
ok("S3a חמישי 05:59: שום רישום", gt.autoreg_tick(THU_0559) == [] and not db.get_distribution_batches())
_Fake._today = THU
res = gt.autoreg_tick(THU_0600)
bs = db.get_distribution_batches()
ok("S3b חמישי 06:00: נרשמה אצווה אחת עם כל חברי ה-main", len(res) == 1 and len(bs) == 1
   and db.get_batch_recipients(bs[0]["id"]) and {r["recipient_id"] for r in db.get_batch_recipients(bs[0]["id"])} == rows_before,
   f"{len(res)} {len(bs)}")
ok("S3c בלי שום חלון קופץ", shown == [], str(shown))
ok("S3d המסך יצא ממצב נעילה והצ'יפ 'נעולות' נעלם", not gt._plan_mode() and not gt.chip_plans.isVisibleTo(gt))
ok("S3e הבאנר 'נרשם אוטומטית' גלוי ומציין את התאריך ואת המספר",
   gt.autoreg_banner_frame.isVisibleTo(gt) and "21/10" in gt.lbl_autoreg.text() and f"{len(rows_before)} מקבלים" in gt.lbl_autoreg.text(),
   gt.lbl_autoreg.text())
ok("S3f status_msg דיווח", "נרשמה אוטומטית" in win.statusBar().currentMessage(), win.statusBar().currentMessage())
left = [t for t in (db.get_setting("weekly_extra_ids") or "").split(",") if t]
ok("S3g מי שנרשם הוסר מהבחירות של השבוע", left == [], str(left))
ok("S3h קריאה נוספת בטיימר: כלום", gt.autoreg_tick(THU_0600) == [] and len(db.get_distribution_batches()) == 1)

# ── week_rows לא מושפע, ו"הכול נכון" ───────────────────────────────────────────────
ok("S4a week_rows מחזיר רשימה (לא נשבר) והמסך ללא נעילה", isinstance(gt.week_rows(), list) and not gt._plan_mode())
gt._autoreg_confirm()
ok("S4b 'הכול נכון' מסתיר את הבאנר; האצווה נשארת", not gt.autoreg_banner_frame.isVisibleTo(gt)
   and len(db.get_distribution_batches()) == 1)

# ── חלוקות קודמות ו"תכנונים" ───────────────────────────────────────────────────────
from tabs.distributions import DistributionsTab, BatchDetailsDialog
dt = DistributionsTab(win); dt.refresh()
ok("S5a בטבלת החלוקות האצווה האוטומטית מסומנת 🤖", dt.table.item(0, 1).text().startswith("🤖 "), dt.table.item(0, 1).text())
dlg = BatchDetailsDialog(db.get_distribution_batches()[0], dt)
ok("S5b בפרטי החלוקה יש הסבר שנרשם אוטומטית", any("נרשם אוטומטית" in l.text() for l in dlg.findChildren(type(gt.lbl_autoreg))))
pd = pl.PlansDialog(gt)
ok("S5c חלון 'תכנונים' מציג 'נרשם אוטומטית' ושהנעילה 'בוצעה'",
   pd.table.item(0, 5).text().startswith("נרשם אוטומטית") and pd.table.item(0, 4).text() == "בוצעה",
   f"{pd.table.item(0, 5).text()} / {pd.table.item(0, 4).text()}")

print()
print("FAILED:" if fails else "ALL OK", *fails)
sys.stdout.flush(); os._exit(1 if fails else 0)
