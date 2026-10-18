# -*- coding: utf-8 -*-
"""חלוקת בונוס (18/10/2026): תיבת הסימון במסך החלוקה, הרישום לפי הסימון (holiday="בונוס"),
איפוס התיבה אחרי שמירה, הייבוא ממתנדב, והתג ב'חלוקות קודמות' ובהיסטוריית המקבל.
offscreen, DB זמני.  הרצה: python test_bonus_dist.py  (Python 3.12)"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox, QLabel, QCheckBox
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
asked = []
def _question(*a, **k):
    asked.append(a[2] if len(a) > 2 else "")
    return QMessageBox.StandardButton.Yes
QMessageBox.question = staticmethod(_question)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

import holidays
ids = []
for i in range(8):
    ids.append(db.add_recipient({"full_name": f"כהן קבוע{i}", "status": "פעיל", "frequency": "שבועי",
                                 "priority": 4, "souls": 3, "phone1": f"05{i}1111111"}))
db.set_setting("dist_regulars_mode", "schedule")
db.set_setting("available_products", "50")
db.set_setting("last_distributor", "מחלק בדיקה")
from main import MainWindow
win = MainWindow()
gt, st, dt = win.group_tab, win.search_tab, win.distributions_tab
gt.refresh(); gt._needs_refresh = False

# ── 1. התיבה קיימת, כבויה כברירת מחדל ───────────────────────────────────────────
chk = getattr(gt, "chk_bonus", None)
ok("B1 chk_bonus קיימת מסוג QCheckBox", isinstance(chk, QCheckBox))
ok("B1 objectName == chk_bonus", chk is not None and chk.objectName() == "chk_bonus")
ok("B1 כבויה כברירת מחדל", chk is not None and not chk.isChecked())
ok("B1 הטקסט כנדרש", chk is not None and chk.text() == "חלוקת בונוס — לא מזיזה את התור ולא מוציאה מהרשימות", chk.text() if chk else "")
ok("B1 יש tooltip", chk is not None and len(chk.toolTip()) > 10)

def record(pick_ids, name, bonus):
    """כמו המפעיל: שלב הרישום, סימון מי שקיבל, שמירה."""
    gt.refresh()
    gt._set_stage("record")
    gt._checked_ids.clear()
    gt._checked_ids |= set(pick_ids)
    gt._populate()
    gt.dist_input.setCurrentText("מחלק בדיקה")
    gt.name_input.setCurrentText(name)
    gt.chk_bonus.setChecked(bonus)
    asked.clear()
    gt._save()

def batch_named(name):
    return next(b for b in db.get_distribution_batches() if b.get("dist_name") == name)

# ── 2. שמירה כשהתיבה מסומנת → "בונוס" באצווה ובשורות ────────────────────────────
record(ids[:2], "בונוס בדיקה", True)
b = batch_named("בונוס בדיקה")
ok("B2 האצווה נרשמה עם holiday == 'בונוס'", b.get("holiday") == "בונוס", repr(b.get("holiday")))
rows = db.get_batch_recipients(b["id"])
ok("B2 שתי השורות נרשמו", len(rows) >= 2, str(len(rows)))
all_rows = [d for d in db.get_distributions() if d.get("batch_id") == b["id"]] \
    if db.get_distributions() and "batch_id" in db.get_distributions()[0] else \
    [d for d in db.get_distributions() if d.get("dist_name") == "בונוס בדיקה"]
ok("B2 כל שורת חלוקה נושאת 'בונוס'", bool(all_rows) and all(d.get("holiday") == "בונוס" for d in all_rows),
   f"{len(all_rows)} שורות")
ok("B2 חלון האישור מציין חלוקת בונוס", any("חלוקת בונוס" in str(m) for m in asked), str(asked))
ok("B2 הבונוס זוהה כחלוקה נוספת", holidays.is_extra_dist(b) and holidays.is_bonus_dist(b)
   and not holidays.is_holiday_dist(b))

# ── 3. אחרי שמירה התיבה מתאפסת ─────────────────────────────────────────────────
ok("B3 התיבה התאפסה אחרי שמירה", not gt.chk_bonus.isChecked())

# ── 4. שמירה בלי סימון → '' ────────────────────────────────────────────────────
record(ids[2:4], "רגילה בדיקה", False)
b2 = batch_named("רגילה בדיקה")
ok("B4 האצווה הרגילה נרשמה עם holiday ריק", (b2.get("holiday") or "") == "", repr(b2.get("holiday")))
ok("B4 חלון האישור לא מזכיר בונוס", not any("בונוס" in str(m) for m in asked), str(asked))
ok("B4 לא נחשבת חלוקה נוספת", not holidays.is_extra_dist(b2))
ok("B4 התיבה נשארת כבויה", not gt.chk_bonus.isChecked())

# ── 5. ייבוא קובץ מתנדב: לפי התיבה הנוכחית ─────────────────────────────────────
from utils.excel_utils import export_volunteer_checklist_to_excel
def volunteer(pick_ids, name, bonus):
    recs = [db.get_recipient(i) for i in pick_ids]
    path = export_volunteer_checklist_to_excel(recs, "2026-10-21", name, "סל מזון", 25, "מתנדב")
    gt.chk_bonus.setChecked(bonus)
    try:
        n, _meta, _ids, _ = gt._apply_checklist_file(path, confirm=True)
    finally:
        try: os.remove(path)
        except OSError: pass
    return n
n = volunteer(ids[4:6], "מתנדב בונוס", True)
ok("B5 ייבוא מתנדב עם התיבה מסומנת → בונוס", n == 2 and batch_named("מתנדב בונוס").get("holiday") == "בונוס",
   repr(batch_named("מתנדב בונוס").get("holiday")))
n = volunteer(ids[6:8], "מתנדב רגיל", False)
ok("B5 ייבוא מתנדב בלי סימון → רגיל", n == 2 and (batch_named("מתנדב רגיל").get("holiday") or "") == "",
   repr(batch_named("מתנדב רגיל").get("holiday")))
gt.chk_bonus.setChecked(True); gt._after_round_recorded()
ok("B5 _after_round_recorded מאפס תיבה מסומנת", not gt.chk_bonus.isChecked())

# ── 6. תג בחלוקות קודמות ───────────────────────────────────────────────────────
from tabs.distributions import BatchDetailsDialog
def head_text(batch):
    d = BatchDetailsDialog(batch)
    return " ".join(l.text() for l in d.findChildren(QLabel))
t = head_text(batch_named("בונוס בדיקה"))
ok("B6 תג בונוס: 🎁 + 'חלוקת בונוס' + הטקסט הקיים",
   "🎁" in t and "חלוקת בונוס" in t and "חלוקה נוספת — לא מזיזה את התור הקבוע" in t and "🎉" not in t, t[:160])
t = head_text(batch_named("רגילה בדיקה"))
ok("B6 חלוקה רגילה: אין תג", "חלוקה נוספת" not in t and "🎁" not in t and "🎉" not in t)
db.bulk_add_distributions([db.get_recipient(ids[0])], "2026-04-01", "", 0, "מחלק", dist_name="פסח בדיקה", holiday="פסח")
t = head_text(batch_named("פסח בדיקה"))
ok("B6 חלוקת חג: 🎉 'חלוקת פסח' (לא 🎁)", "🎉" in t and "חלוקת פסח" in t and "🎁" not in t, t[:160])

# ── 7. היסטוריית מקבל ───────────────────────────────────────────────────────────
def hist_texts(rec_id):
    st._show_recipient(rec_id)
    out = []
    for r in range(st.hist_table.rowCount()):
        out.append(" | ".join((st.hist_table.item(r, c).text() if st.hist_table.item(r, c) else "")
                              for c in range(st.hist_table.columnCount())))
    return out
h = hist_texts(ids[0])
ok("B7 היסטוריית מקבל הבונוס מציגה '🎁 חלוקת בונוס'", any("🎁 חלוקת בונוס" in x for x in h), str(h)[:200])
ok("B7 ... וחלוקת החג עם 🎉", any("🎉 חלוקת פסח" in x for x in h), str(h)[:200])
h2 = hist_texts(ids[2])
# (הוא היה גם ברשימת הבונוס כ"לא הגיע" — לכן שורה אחת מתויגת; השורה של החלוקה הרגילה בלי תג)
ok("B7 החלוקה הרגילה של אותו מקבל: שורה בלי תג", any(x.split(" | ")[1] == "" for x in h2), str(h2)[:200])

print("\nFAILED: " + ", ".join(fails) if fails else "\nALL BONUS-DIST CHECKS PASS ✓")
sys.exit(1 if fails else 0)
