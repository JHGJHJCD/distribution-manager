# -*- coding: utf-8 -*-
"""משימה 6: סטטוס המקבל רק פעיל/מושהה — צילום כרטיס המקבל (עם ערך ישן גולמי),
רשימת הנפתח של הסטטוס, וסינון הסטטוס ברשימת "כל המקבלים". DB זמני, בלי offscreen."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()
app = QApplication(sys.argv); app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
from styles import apply_app_theme
apply_app_theme(app, 100)
from tabs.recipients import RecipientDialog

OUT = os.path.join(os.path.dirname(__file__), "_shots"); os.makedirs(OUT, exist_ok=True)

def grab_ok(w, path, tries=4):
    for _ in range(tries):
        for _ in range(8):
            app.processEvents()
        w.grab().save(path)
        if os.path.getsize(path) > 15000:
            return
        apply_app_theme(app, 100); w.repaint()
    raise AssertionError("grab too small: " + path)

# כרטיס שנטען עם ערך ישן גולמי — חייב להיפתח "מושהה"
rec = {"full_name": "כהן ישראל", "first_name": "ישראל", "last_name": "כהן", "priority": 4,
       "frequency": "שבועי", "status": "הסתיים", "phone1": "0501234567"}
dlg = RecipientDialog(None, rec)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show()
grab_ok(dlg, os.path.join(OUT, "status_card.png"))
items = [dlg.f_status.itemText(i) for i in range(dlg.f_status.count())]
print("card combo:", items, "| current:", dlg.f_status.currentText(), "| chip:", dlg.chip_state.text())
assert items == ["פעיל", "מושהה"] and dlg.f_status.currentText() == "מושהה"
assert "מושהה" in dlg.chip_state.text()

# רשימת הנפתח עצמה
dlg.f_status.showPopup(); app.processEvents(); app.processEvents()
view = dlg.f_status.view()
view.grab().save(os.path.join(OUT, "status_popup.png"))
dlg.f_status.hidePopup()

# סינון הסטטוס ברשימת כל המקבלים (החלון הראשי)
db.add_recipient({"full_name": "לוי חי", "status": "פעיל", "frequency": "שבועי", "priority": 4})
db.add_recipient({"full_name": "דוד מושהה", "status": "מושהה", "frequency": "שבועי", "priority": 4})
from main import MainWindow
win = MainWindow()
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1366, 800); win.show()
win.navigate_to_tab(win.recipients_tab)
QTest.qWait(450)
rt = win.recipients_tab
fitems = [rt.status_filter.itemText(i) for i in range(rt.status_filter.count())]
print("filter combo:", fitems)
assert fitems == ["הכל", "פעיל", "מושהה"]
rt.status_filter.setCurrentText("מושהה"); QTest.qWait(200)
print("suspended filter rows:", rt.table.rowCount())
assert rt.table.rowCount() == 1
rt.status_filter.setCurrentText("הכל"); QTest.qWait(200)
grab_ok(win, os.path.join(OUT, "status_list.png"))
print("OK")
