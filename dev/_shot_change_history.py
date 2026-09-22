# -*- coding: utf-8 -*-
"""v3.63 — היסטוריית שינויים בכרטיס: חיפוש מהיר (שורת השינויים + כפתור), חלון
ההיסטוריה, וכפתור בכרטיס המקבל. assert-ים + צילומים ל-dev/_shots (לאמת דרך Gemini)."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtCore import Qt
import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()
app = QApplication(sys.argv); app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
from styles import apply_app_theme
apply_app_theme(app, 100)
from tabs.search import SearchTab
from tabs.recipients import RecipientDialog
from widgets import ChangeHistoryDialog

OUT = os.path.join(os.path.dirname(__file__), "_shots"); os.makedirs(OUT, exist_ok=True)

def show(w, name, size=None, min_bytes=20_000):
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    if size: w.resize(*size)
    w.show(); app.processEvents()
    p = os.path.join(OUT, name); w.grab().save(p)
    assert os.path.getsize(p) > min_bytes, name

rid = db.add_recipient({"full_name": "כהן ישראל", "first_name": "ישראל", "last_name": "כהן",
                        "phone1": "0501234567", "income": "1,000", "souls": 4, "priority": 4,
                        "frequency": "שבועי", "status": "פעיל", "address": "הרצל 3"})
db.update_recipient(rid, {"income": "2,000"})
db.update_recipient(rid, {"souls": 5, "address": "הרצל 3 דירה 8"})
db.update_recipient(rid, {"status": "מושהה"})
rec = db.get_recipient(rid)
chs = db.get_changes_for_recipient(rid, rec["guid"])
assert len(chs) == 4 and chs[0]["field"] == "status", [(c["field"]) for c in chs]

tab = SearchTab()
tab.refresh(); app.processEvents()
tab._show_recipient(rid); app.processEvents()
assert tab.btn_changes.isEnabled()
assert "שינויים בכרטיס: 4" in tab.lbl_changes.text() and "סטטוס" in tab.lbl_changes.text(), tab.lbl_changes.text()
assert "פעיל" in tab.lbl_changes.text() and "מושהה" in tab.lbl_changes.text()
show(tab, "changes_search.png", (1280, 800))
tab._show_empty_profile(); app.processEvents()
assert not tab.btn_changes.isEnabled() and tab.lbl_changes.text() == ""

dlg = ChangeHistoryDialog(rec, None)
assert dlg.table.rowCount() == 4 and dlg.table.item(0, 1).text() == "סטטוס"
assert dlg.table.item(3, 2).text() == "1,000" and dlg.table.item(3, 3).text() == "2,000"
assert dlg.table.item(0, 4).text() == "עריכה"
show(dlg, "changes_dialog.png")
# סינון לפי שדה
dlg.cmb_field.setCurrentIndex(dlg.cmb_field.findData("income")); app.processEvents()
assert dlg.table.rowCount() == 1 and "מוצגים 1" in dlg.lbl_sub.text(), dlg.lbl_sub.text()
# מקבל בלי היסטוריה — הודעת מצב-ריק
rid2 = db.add_recipient({"full_name": "לוי משה", "phone1": "0502222222"})
dlg2 = ChangeHistoryDialog(db.get_recipient(rid2), None)
assert dlg2.table.rowCount() == 0 and dlg2.lbl_empty.isVisibleTo(dlg2) and not dlg2.table.isVisibleTo(dlg2)
show(dlg2, "changes_dialog_empty.png", min_bytes=4_000)
# כרטיס מקבל: כפתור רק בעריכה
edit = RecipientDialog(None, rec); show(edit, "changes_recipient_edit.png")
assert edit.btn_changes.isVisibleTo(edit)
add = RecipientDialog(None)
assert not add.btn_changes.isVisibleTo(add)
print("OK", [os.path.join(OUT, n) for n in ("changes_search.png", "changes_dialog.png",
                                            "changes_dialog_empty.png", "changes_recipient_edit.png")])
