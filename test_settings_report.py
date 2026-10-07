# -*- coding: utf-8 -*-
"""דוח 7/10/2026 חבילה ד': משקלי ניקוד חופשיים עם חסימת שמירה (ד1), אחוזי קהילות
שגויים חוסמים שמירה (ד2), לשוניות צד בהגדרות (ד3). offscreen, DB זמני."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
app = QApplication(sys.argv)
fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

from tabs.settings import SettingsTab, CommunityQuotasDialog
st = SettingsTab(None); st.refresh()
keys = [f["key"] for f in db.NEED_FACTORS]

# ── ד1 ──
st._load_weights()
ok("D1a loaded total is 100 and save enabled", st._weights_total() == 100 and st.btn_save_weights.isEnabled())
for i, k in enumerate(keys):
    st._weight_spins[k].setValue(0)
st._weight_spins[keys[0]].setValue(25); st._weight_spins[keys[1]].setValue(25)
ok("D1b typing does not rebalance the others",
   st._weight_spins[keys[0]].value() == 25 and st._weight_spins[keys[1]].value() == 25
   and all(st._weight_spins[k].value() == 0 for k in keys[2:]))
ok("D1c total 50 -> save blocked + 'חסרים 50%'",
   not st.btn_save_weights.isEnabled() and "חסרים 50%" in st.lbl_weight_preview.text(),
   st.lbl_weight_preview.text())
before = dict(db.get_need_weights())
st._save_weights()
ok("D1d forced save with 50 writes nothing", db.get_need_weights() == before)
st._weight_spins[keys[2]].setValue(100)
ok("D1e total 150 -> 'עודפים 50%' and blocked",
   not st.btn_save_weights.isEnabled() and "עודפים 50%" in st.lbl_weight_preview.text())
st._weight_spins[keys[2]].setValue(50)
ok("D1f exactly 100 (25/25/50) -> enabled", st.btn_save_weights.isEnabled())
st._save_weights()
w = db.get_need_weights()
ok("D1g saved 25/25/50 as typed", w.get(keys[0]) == 25 and w.get(keys[1]) == 25 and w.get(keys[2]) == 50, str(w))
st._reset_weights()
ok("D1h reset still works", st._weights_total() == 100 and st.btn_save_weights.isEnabled())

# ── ד2 ──
for i, name in enumerate(["נציג א", "נציג ב", "נציג ג"]):
    for j in range(2):
        db.add_recipient({"full_name": f"משפחה{i}{j}", "status": "פעיל", "frequency": "שבועי",
                          "priority": 4, "souls": 2, "representative": name,
                          "phone1": f"05{i}{j}1234567"})
dlg = CommunityQuotasDialog(None)
sp = dlg._spins
ok("D2a three communities", len(sp) == 3, str(list(sp)))
cs = list(sp)
sp[cs[0]].setValue(50); sp[cs[1]].setValue(80)
ok("D2b 50+80 -> wrong, save blocked",
   not dlg.btn_save.isEnabled() and "אחוזים שגויים" in dlg.lbl_total.text(), dlg.lbl_total.text())
dlg._save()
ok("D2c forced save writes nothing", not db.get_community_quotas())
sp[cs[1]].setValue(30)
ok("D2d 50+30 with one automatic -> ok", dlg.btn_save.isEnabled())
sp[cs[2]].setValue(10)
ok("D2e all manual, total 90 -> wrong", not dlg.btn_save.isEnabled())
sp[cs[2]].setValue(20)
ok("D2f all manual, total 100 -> ok", dlg.btn_save.isEnabled())
dlg.accept = lambda: None
dlg._save()
ok("D2g saved", sum(db.get_community_quotas().values()) == 100, str(db.get_community_quotas()))

# ── ד3 ──
names = [st.nav_list.item(i).text() for i in range(st.nav_list.count())]
ok("D3a categories", len(names) == st.page_stack.count() >= 5, str(names))
for i in range(len(names)):
    st.nav_list.setCurrentRow(i)
    ok(f"D3b page {i} shown ({names[i]})", st.page_stack.currentIndex() == i)
for a in ("org_title", "mail_email", "no_show_spin", "_weight_spins", "btn_feedback",
          "lbl_google_status", "btn_mgr_toggle", "chip_version"):
    ok(f"D3c attribute kept: {a}", hasattr(st, a))

print("\nFAILED:" if fails else "\nALL OK", fails if fails else "")
sys.exit(1 if fails else 0)
