"""Screenshot probe (task 7): the three "same name, different phone" merge offers.

  1. בדיקת כפילויות (ReviewTab) — the tab + the real ask_choice dialog of "מזג כפילות"
  2. ייבוא אקסל — ImportReviewDialog with the same-name/different-phone table
  3. הוספה ידנית — the real ask_choice shown by RecipientDialog on save

Temp DB only. QMessageBox.exec is replaced by a grab, so the REAL code paths build the
dialogs. Saves dev/_shots/merge_*.png.  Run: python dev/_shot_merge_dialogs.py
(Python 3.12, PYTHONUTF8=1, NOT offscreen)
"""
import os
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

from PyQt6.QtWidgets import QApplication, QMessageBox, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

app = QApplication.instance() or QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
import styles
styles.apply_app_theme(app, 100)
app.setFont(QFont("Segoe UI", 11))
from utils import ui
ui.install_hebrew_ui(app)

import database as db
tmp = tempfile.mkdtemp(prefix="merge_shot_")
db.DB_PATH = os.path.join(tmp, "data.db")
db.BACKUP_DIR = os.path.join(tmp, "backups")
db.init_db()

OUT = os.path.join(REPO, "dev", "_shots")
os.makedirs(OUT, exist_ok=True)


def grab(w, name, size=None):
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    if size:
        w.resize(*size)
    w.show()
    for _ in range(6):
        app.processEvents()
    path = os.path.join(OUT, name)
    ok = w.grab().save(path)
    sz = os.path.getsize(path)
    assert ok and sz > 8000, (name, sz)
    print("saved", path, sz)
    return path


_box_shots = {}


def fake_exec(self):
    _box_shots["last"] = grab(self, _box_shots["name"])
    # measure: every button must be wide enough for its caption (no clipped letters)
    for b in self.buttons():
        need = b.fontMetrics().horizontalAdvance(b.text())
        print("  button %-32r width=%d text=%d margin=%d" % (b.text(), b.width(), need, b.width() - need))
        assert b.width() - need >= 16, ("button text clipped", b.text(), b.width(), need)
    return 0


QMessageBox.exec = fake_exec

# ── seed: a same-name pair with different phones + history ───────────────────
xid = db.add_recipient({"full_name": "כהן דוד", "first_name": "דוד", "last_name": "כהן",
                        "phone1": "0501111111", "frequency": "שבועי", "priority": 4,
                        "address": "רחוב הנחל 1", "souls": 5})
yid = db.add_recipient({"full_name": "כהן דוד", "first_name": "דוד", "last_name": "כהן",
                        "phone1": "0522222222", "address": "רחוב הגפן 7", "email": "d@example.com"})
x, y = db.get_recipient(xid), db.get_recipient(yid)
db.bulk_add_distributions([dict(x)], "2026-08-05", "מארז", 1, "משה", dist_name="א")
db.bulk_add_distributions([dict(x)], "2026-08-12", "מארז", 1, "משה", dist_name="ב")
db.bulk_add_distributions([dict(y)], "2026-08-19", "מארז", 1, "משה", dist_name="ג")

# 1. review tab ---------------------------------------------------------------
from tabs.review import ReviewTab
rev = ReviewTab(None)
rev.refresh()
rev.table.setCurrentCell(0, 2)
grab(rev, "merge_review_tab.png", (960, 420))
_box_shots["name"] = "merge_review_ask.png"
rev._merge()                      # real flow → ask_choice → fake_exec grabs it
assert len(db.get_all_recipients()) == 2, "the ask dialog must not merge by itself"

# 2. import dialog ------------------------------------------------------------
from tabs.recipients import ImportReviewDialog
rows = [{"full_name": "כהן דוד", "phone1": "0533333333", "email": "new@example.com"},
        {"full_name": "לוי משה", "phone1": "0544444444", "address": "חדש"}]
db.add_recipient({"full_name": "לוי משה", "phone1": "0548888888", "address": "ישן"})
diff = db.diff_incoming_recipients(rows)
print("same_name:", [s["full_name"] for s in diff["same_name"]])
# (כהן דוד has two cards → ambiguous, skipped by design; לוי משה is the same-name row)
assert [s["full_name"] for s in diff["same_name"]] == ["לוי משה"], diff["same_name"]
dlg = ImportReviewDialog(diff)
grab(dlg, "merge_import_dialog.png", (860, 640))
t = dlg._same_table
cb = dlg._same_combos[0]
box = t.widget()
print("same_name area: h=%d viewport=%d box=%d combo=%s mapped_bottom=%d" % (
    t.height(), t.viewport().height(), box.height(), cb.geometry().getRect(), cb.geometry().bottom()))
assert t.viewport().height() >= box.sizeHint().height() - 2, "same-name rows are clipped"
for child in box.findChildren(QLabel):
    assert child.width() >= child.fontMetrics().horizontalAdvance(child.text()), ("label clipped", child.text())
assert dlg.selected_same_name()[0]["choice"] == "separate"       # default = the safe one

# 3. manual add ---------------------------------------------------------------
from tabs.recipients import RecipientDialog
add = RecipientDialog(None)
add.f_first.setText("משה")
add.f_last.setText("לוי")
add.f_phone1.setText("0555555555")
add.f_priority.setCurrentIndex(1)       # קבוע (so the "לא בחלוקה" warning does not appear)
_box_shots["name"] = "merge_add_ask.png"
add._validate_and_accept()               # real flow → ask_choice (fake_exec → "back to edit")
assert add.merge_into_id is None and add.result() != add.DialogCode.Accepted
print("done")
