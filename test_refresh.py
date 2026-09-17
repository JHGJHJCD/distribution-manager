# -*- coding: utf-8 -*-
"""ריענון נתונים בין מסכים (v3.62): אחרי שינוי במסך אחד — כל מסך אחר מציג נתון
עדכני, ורענון (סנכרון) לא הורס את מה שהמשתמש רואה/מקליד. offscreen, DB זמני."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

for i in range(4):
    db.add_recipient({"full_name": f"כהן קבוע{i}", "status": "פעיל", "frequency": "חודשי",
                      "priority": 4, "souls": 3, "phone1": f"05{i}1111111"})
db.add_recipient({"full_name": "לוי אחר", "status": "פעיל", "frequency": "שבועי",
                  "priority": 4, "souls": 2, "phone1": "0541234567"})
db.set_setting("dist_regulars_mode", "schedule")
from main import MainWindow
win = MainWindow()
gt, tz, ml = win.group_tab, win.tzintukim_tab, win.mails_tab
rt, st, dt = win.recipients_tab, win.search_tab, win.distributions_tab
gt.refresh(); gt._needs_refresh = False

def names(rows):
    return {r.get("full_name") for r in rows}

# ── R1: עריכה במסך אחר → צינתוקים קורא רשימה עדכנית בלי לבקר ב"חלוקה" ──────────
win.navigate_to_tab(rt)
rec = next(r for r in db.get_all_recipients() if r["full_name"] == "לוי אחר")
db.update_recipient(rec["id"], {**rec, "phone1": "0549999999"})
new_id = db.add_recipient({"full_name": "חדש שנוסף", "status": "פעיל", "frequency": "שבועי",
                           "priority": 4, "souls": 1, "phone1": "0521111222"})
win.refresh_all()                       # כמו אחרי שמירת כרטיס / סנכרון
ok("R1a group tab only flagged (lazy)", gt._needs_refresh is True)
tz._load_week_list()
tz_names = {r["rec"].get("full_name") for r in tz._rows}
ok("R1b tzintuk list has the new recipient", "חדש שנוסף" in tz_names, str(len(tz_names)))
lv = next(r for r in tz._rows if r["rec"].get("full_name") == "לוי אחר")
ok("R1c tzintuk dials the corrected phone", lv["phones"] == ["0549999999"], str(lv["phones"]))
ok("R1d week_rows cleared the stale flag", gt._needs_refresh is False)

# ── R2: שינוי מקומי ב"חלוקה" מסמן צינתוקים/מיילים לרענון ─────────────────────
win.navigate_to_tab(gt)
tz._needs_refresh = False; ml._needs_refresh = False
gt.refresh()
ok("R2 group refresh flags tzintuk+mails", tz._needs_refresh and ml._needs_refresh)

# ── R3: חריג שתוקן חוזר מסומן; הוספה ידנית נבנית מחדש מהכרטיס ────────────────
bad_id = db.add_recipient({"full_name": "בלי טלפון", "status": "פעיל", "frequency": "שבועי",
                           "priority": 4, "souls": 1})
gt.refresh(); tz.refresh()
row = next(r for r in tz._rows if r["rec"].get("id") == bad_id)
ok("R3a exception row starts unchecked", row["checked"] is False and bool(row["why"]))
b = db.get_recipient(bad_id)
db.update_recipient(bad_id, {**b, "phone1": "0533334444"})
gt.refresh(); tz.refresh()
row = next(r for r in tz._rows if r["rec"].get("id") == bad_id)
ok("R3b fixed row is checked & ready", row["checked"] is True and not row["why"], str(row["why"]))
# בחירת-מפעיל (ביטול סימון של שורה תקינה) עדיין שורדת רענון
row["checked"] = False
tz.refresh()
row = next(r for r in tz._rows if r["rec"].get("id") == bad_id)
ok("R3c operator's un-tick survives refresh", row["checked"] is False)

man_id = db.add_recipient({"full_name": "ידני מחוץ", "status": "פעיל", "frequency": "",
                           "souls": 1, "phone1": "0501010101"})
tz._rows.append(tz._make_row(dict(db.get_recipient(man_id)), manual=True))
m = db.get_recipient(man_id)
db.update_recipient(man_id, {**m, "phone1": "0502020202"})
tz.refresh()
mrow = next((r for r in tz._rows if r["rec"].get("id") == man_id), None)
ok("R3d manual row rebuilt from the card", mrow is not None and mrow["phones"] == ["0502020202"]
   and mrow["manual"], str(mrow and mrow["phones"]))
db.delete_recipient(man_id)
tz.refresh()
ok("R3e deleted manual row dropped", all(r["rec"].get("id") != man_id for r in tz._rows))

# ── R4: מחיקת חלוקה / רישום-חלוקה מרעננת את כל המסכים ─────────────────────────
ids = [r["id"] for r in db.get_all_recipients() if r["full_name"].startswith("כהן")]
from datetime import timedelta
OLD_WED = (db.next_wednesday() - timedelta(days=14)).isoformat()   # חודשי ⇒ התור הבא עוד שבועיים
db.bulk_add_distributions([db.get_recipient(i) for i in ids], OLD_WED, "", "", "",
                          dist_name="בדיקה", general_note="")
win.refresh_all()
win.navigate_to_tab(gt)
ok("R4a recorded regulars left the week list",
   not any(n.startswith("כהן") for n in names(gt._rows_data)))
win.navigate_to_tab(dt)
dt.table.setCurrentCell(0, 0)
for t in win._leaf_tabs:
    t._needs_refresh = False
dt._delete_selected()
ok("R4b delete batch flags the distribution screen", gt._needs_refresh is True)
win.navigate_to_tab(gt)
ok("R4c regulars are back on the week list",
   sum(1 for n in names(gt._rows_data) if n.startswith("כהן")) == 4)

ok("R4d search tab knows the main window", getattr(st, "main_win", None) is win)
db.bulk_add_distributions([db.get_recipient(ids[0])], OLD_WED, "", "", "",
                          dist_name="בדיקה 2", general_note="")
win.refresh_all()
win.navigate_to_tab(st)
st.search_input.setText(""); st._run_search()
for i in range(st.results_list.count()):
    if st.results_list.item(i).data(Qt.ItemDataRole.UserRole) == ids[0]:
        st.results_list.setCurrentRow(i)
st.hist_table.setCurrentCell(0, 0)
for t in win._leaf_tabs:
    t._needs_refresh = False
try:
    st._delete_hist_record()
    crashed = False
except Exception as e:                       # noqa: BLE001
    crashed = True; print("     ", repr(e))
ok("R4e delete single record doesn't crash", not crashed)
ok("R4f …and flags the other screens", gt._needs_refresh is True)
ok("R4g search stays on the same person", st._current_rec_id == ids[0], str(st._current_rec_id))

# ── R5: "כל המקבלים" — רענון שומר חיפוש/בחירה; בדיקת כפילויות לא מרוקנת ─────
win.navigate_to_tab(rt)
rt.search_input.setText("כהן"); rt._apply_filter()
n_filtered = rt.table.rowCount()
rt.table.setCurrentCell(2, 1)
sel = rt._selected_id()
rt.refresh()
ok("R5a refresh keeps the search filter", rt.table.rowCount() == n_filtered == 4,
   f"{rt.table.rowCount()} / {n_filtered}")
ok("R5b refresh keeps the selected person", rt._selected_id() == sel)
from PyQt6.QtWidgets import QDialog
_orig_exec = QDialog.exec
QDialog.exec = lambda self: 0
try:
    rt._open_dup_check()
finally:
    QDialog.exec = _orig_exec
rt.search_input.setText("לוי"); rt._apply_filter()
ok("R5c search still works after the duplicates dialog", rt.table.rowCount() == 1,
   str(rt.table.rowCount()))

# ── R6: הגדרות — רענון לא דורס הקלדה; סף אי-הגעה מסמן מסכים ─────────────────
sg = win.settings_tab
win.navigate_to_tab(sg)
sg.org_title.setText("")
sg.org_title.setFocus()
sg.org_title.insert("שם חדש שטרם נשמר")       # insert() = הקלדת משתמש (modified)
sg.refresh()
ok("R6a sync refresh keeps the typed title", sg.org_title.text() == "שם חדש שטרם נשמר")
k = next(iter(sg._weight_spins))
sg._weight_spins[k].setValue(sg._weight_spins[k].value() + 7 if sg._weight_spins[k].value() < 90 else 50)
typed = sg._weight_spins[k].value()
sg.refresh()
ok("R6b sync refresh keeps unsaved weights", sg._weight_spins[k].value() == typed)
for t in win._leaf_tabs:
    t._needs_refresh = False
sg.no_show_spin.setValue(5 if sg.no_show_spin.value() != 5 else 4)
ok("R6c no-show threshold flags the other screens", gt._needs_refresh and st._needs_refresh)
db.set_setting("no_show_alert_threshold", "2")
sg.refresh()
ok("R6d threshold from the other computer is shown", sg.no_show_spin.value() == 2)

# ── R7: מצב חלוקה שהוחלף במחשב השני נקלט ברענון ───────────────────────────────
db.set_setting("dist_regulars_mode", "none")
gt.refresh()
ok("R7 mode combo follows the synced setting", gt._current_mode() == "none", gt._current_mode())
db.set_setting("dist_regulars_mode", "schedule"); gt.refresh()

# ── R8: בחירה ידנית של מקבל שנמחק לא נשמרת כמספר מקומי ───────────────────────
gone = db.add_recipient({"full_name": "יימחק", "status": "פעיל", "frequency": "חד-פעמי",
                         "priority": 3, "souls": 1})
gt._extra_ids.add(gone)
db.delete_recipient(gone)
gt._persist_extras()
ok("R8 deleted pick isn't persisted as a bare local id",
   str(gone) not in (db.get_setting("weekly_extra_ids") or "").split(","))

print()
print("נכשלו: " + ", ".join(fails) if fails else "הכל עבר ✓")
sys.exit(1 if fails else 0)
