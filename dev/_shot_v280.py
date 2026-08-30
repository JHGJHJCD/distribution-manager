# -*- coding: utf-8 -*-
"""Visual probe for v2.80: text-size percent (instant), sync status card,
feedback inbox dialog. WA_DontShowOnScreen + grab() on a temp DB."""
import os
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

d = tempfile.mkdtemp()
import database as db
db.DB_PATH = os.path.join(d, "shot.db")
db.BACKUP_DIR = os.path.join(d, "backups")
db.init_db()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
import styles

app = QApplication.instance() or QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
styles.apply_app_theme(app, 100)

# Seed: sync enabled (amber state — no second machine) + feedback messages.
from utils import sync
shared = os.path.join(d, "shared")
sync.enable_sync(shared, seed=False)
sync.run_sync()
db.add_feedback("ההדפסה יוצאת חתוכה בצד ימין", author_name="מזכירה", host="PC-OFFICE",
                version="2.79")
db.add_feedback("אשמח שאפשר יהיה לייצא גם ל-PDF מהחיפוש", author_name="מנהל",
                host="PC-HOME", version="2.79")
fid = db.add_feedback("הודעה ישנה שכבר טופלה", author_name="", host="PC-OFFICE",
                      version="2.78")
done_guid = next(f["guid"] for f in db.get_feedback() if f["body"].startswith("הודעה ישנה"))
db.set_feedback_status(done_guid, "done")

from main import MainWindow
win = MainWindow()
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 880)
win.show()
app.processEvents(); app.processEvents()

out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)

leaves = {t.objectName(): t for t in getattr(win, "_leaf_tabs", [])}
settings_tab = leaves.get("tab_settings")
win.navigate_to_tab(settings_tab)
settings_tab.refresh()
# A fresh style repolish wakes the scroll-area content in WA_DontShowOnScreen mode.
styles.apply_app_theme(app, 100)
for _ in range(4):
    app.processEvents()
win.grab().save(os.path.join(out, "v280_settings_100.png"))
print("shot: v280_settings_100.png")

from PyQt6.QtWidgets import QScrollArea
scroll = settings_tab.findChild(QScrollArea)
if scroll:
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    app.processEvents(); app.processEvents()
    win.grab().save(os.path.join(out, "v280_settings_sync_100.png"))
    print("shot: v280_settings_sync_100.png")

# Instant rescale to 130% — same run, no restart.
styles.apply_app_theme(app, 130)
for _ in range(4):
    app.processEvents()
if scroll:
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    app.processEvents(); app.processEvents()
win.grab().save(os.path.join(out, "v280_settings_sync_130.png"))
print("shot: v280_settings_sync_130.png")

# Back to 100% and grab the feedback inbox dialog.
styles.apply_app_theme(app, 100)
from tabs.settings import FeedbackInboxDialog
dlg = FeedbackInboxDialog(settings_tab)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.resize(900, 620)
dlg.show()
app.processEvents()
dlg.table.setCurrentCell(1, 0)
app.processEvents(); app.processEvents()
print("preview text len:", len(dlg.preview.toPlainText()))
dlg.grab().save(os.path.join(out, "v280_feedback_inbox.png"))
print("shot: v280_feedback_inbox.png")
print("done")
