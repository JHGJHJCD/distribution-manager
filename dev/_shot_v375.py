# -*- coding: utf-8 -*-
"""v3.75 — DeletedRecipientsDialog + BatchDetailsDialog (holiday tag) + settings sender name.
Real (non-offscreen) render with WA_DontShowOnScreen + grab(), throwaway DB. Asserts + PNGs."""
import os, sys, tempfile
os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8")
os.chdir(r"C:\Users\יהודה\Desktop\מנהל_חלוקה"); sys.path.insert(0, ".")
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
QMessageBox.information = staticmethod(lambda *a, **k: None)
app = QApplication(sys.argv)
import styles
styles.apply_app_theme(app, 100)
OUT = os.path.join("dev", "_shots"); os.makedirs(OUT, exist_ok=True)

def show(w, name, size=None):
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    if size: w.resize(*size)
    w.show(); app.processEvents(); app.processEvents()
    pix = w.grab(); p = os.path.join(OUT, name); pix.save(p)
    assert os.path.getsize(p) > 2000, name
    print("shot:", name)

# data
rid = db.add_recipient({"full_name": "ישראלי משה", "status": "פעיל", "phone1": "0501234567", "souls": 5, "priority": 4,
                        "frequency": "דו-שבועי"})
rid2 = db.add_recipient({"full_name": "לוי דוד", "status": "פעיל", "phone1": "0522222222", "souls": 3})
bid = db.bulk_add_distributions([db.get_recipient(rid)], "2026-04-01", "מארז פסח", 1, "יוסי",
                                dist_name="חלוקת פסח — י״ד ניסן תשפ״ו", holiday="פסח",
                                not_received=[db.get_recipient(rid2)])
rid3 = db.add_recipient({"full_name": "כהן יעקב", "status": "פעיל", "phone1": "0533333333", "souls": 2}); db.delete_recipient(rid3)

# 1. deleted recipients dialog
from tabs.settings import DeletedRecipientsDialog
d = DeletedRecipientsDialog()
assert d.table.rowCount() == 1 and d.table.item(0, 1).text() == "כהן יעקב", d.table.rowCount()
assert d.table.item(0, 4).text() == "מחיקה"
show(d, "v375_deleted.png", (820, 420))
d._restore(db.get_deleted_recipients()[0]["guid"])
assert d.table.rowCount() == 0 and d.lbl_empty.isVisibleTo(d) and d.restored
assert any(r["full_name"] == "כהן יעקב" for r in db.get_all_recipients())
show(d, "v375_deleted_empty.png", (820, 420))

# 2. batch details with the holiday tag + names carry ids
from tabs.distributions import BatchDetailsDialog
b = next(x for x in db.get_distribution_batches() if x["id"] == bid)
bd = BatchDetailsDialog(b)
from PyQt6.QtWidgets import QListWidget, QLabel
lists = bd.findChildren(QListWidget)
assert lists and lists[0].item(0).data(Qt.ItemDataRole.UserRole) == rid
assert any("חלוקת פסח" in l.text() and "חלוקה נוספת" in l.text() for l in bd.findChildren(QLabel))
show(bd, "v375_batch_holiday.png", (520, 560))

# 3. search history row shows the tag
from tabs.search import SearchTab
st = SearchTab(); st.refresh(); app.processEvents(); st._show_recipient(rid); app.processEvents()
assert st.hist_table.rowCount() == 1 and st.hist_table.item(0, 1).text().startswith("🎉 חלוקת פסח"), st.hist_table.item(0, 1).text()
print("search history:", st.hist_table.item(0, 1).text())

# 4. settings: sender name field saved via _save_mail_settings_silent
from tabs.settings import SettingsTab
s = SettingsTab(); s.refresh(); app.processEvents()
s.mail_sender_name.setText("קופת הר יונה — חלוקות")
s._save_mail_settings_silent()
from utils import email_utils
assert email_utils.sender_name() == "קופת הר יונה — חלוקות", email_utils.sender_name()
s.mail_sender_name.setText(""); s._save_mail_settings_silent()
assert email_utils.sender_name() == email_utils.SENDER_NAME
assert s.btn_deleted is not None
print("OK v375")
