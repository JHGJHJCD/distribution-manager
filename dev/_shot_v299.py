"""v2.99 visual probe: scored-mode cap, glossy switch/reset button, community
dialog, backups list, print header. Temp DB — never touches real data."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "dev", "_shots")
os.makedirs(OUT, exist_ok=True)

d = tempfile.mkdtemp()
import database as db
db.DB_PATH = os.path.join(d, "shot.db")
db.BACKUP_DIR = os.path.join(d, "backups")
db.init_db()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QColor
import styles
app = QApplication.instance() or QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
styles.apply_app_theme(app, 100)

# seed 12 regulars with different need
for i in range(12):
    db.add_recipient({"full_name": f"משפחה{i} ישראל", "phone1": f"05012345{i:02d}",
                      "frequency": "שבועי", "priority": 4, "status": "פעיל", "souls": 3 + i % 4,
                      "income": str(3000 + i * 700), "children_total": str(i % 6),
                      "representative": "" if i % 3 else "נציג א", "synagogue": "המרכזי"})
db.set_setting("available_products", "5")
db.set_setting("reserve_count", "2")
db.set_setting("dist_mode", "scored")

from main import MainWindow
win = MainWindow()
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1500, 950)
win.show()
for _ in range(4):
    app.processEvents()
tab = [t for t in win._leaf_tabs if t.objectName() == "tab_dist"][0]
# select scored mode explicitly
for i in range(tab.mode_combo.count()):
    if tab.mode_combo.itemData(i) == "scored":
        tab.mode_combo.setCurrentIndex(i)
tab.refresh()
for _ in range(4):
    app.processEvents()
print("rows shown:", len(tab._rows_data), "reserve:",
      sum(1 for r in tab._rows_data if r.get("_reserve")))
print("souls label:", tab.lbl_souls.text(), "| count:", tab.lbl_regulars_count.text())
print("auto name:", tab._effective_dist_name())
win.grab().save(os.path.join(OUT, "v299_dist_scored.png"))
tab._set_stage("record")
for _ in range(3):
    app.processEvents()
win.grab().save(os.path.join(OUT, "v299_dist_record.png"))

from tabs.group_update import CommunityAssignDialog
dlg = CommunityAssignDialog(tab)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show()
for _ in range(3):
    app.processEvents()
dlg.grab().save(os.path.join(OUT, "v299_community.png"))
dlg.close()

from tabs.settings import BackupListDialog
from utils.backup import auto_backup
auto_backup(); auto_backup(kind="safety")
bl = BackupListDialog(win)
bl.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
bl.show()
for _ in range(3):
    app.processEvents()
bl.grab().save(os.path.join(OUT, "v299_backups.png"))
bl.close()

# print HTML → image
from utils import print_view
from PyQt6.QtGui import QTextDocument
rows = tab._get_export_rows()
rows[0]["_confirmed"] = True
html = print_view._build_html(rows, "02/09/2026", True, tab._effective_dist_name())
doc = QTextDocument()
doc.setDefaultStyleSheet(print_view._css(11))
doc.setHtml(html)
from PyQt6.QtCore import QUrl
doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl("orglogo"),
                QImage(os.path.join(ROOT, "org_logo.png")))
doc.setTextWidth(800)
img = QImage(800, 700, QImage.Format.Format_ARGB32)
img.fill(QColor("white"))
p = QPainter(img); doc.drawContents(p); p.end()
img.save(os.path.join(OUT, "v299_print.png"))
print("done")
