# -*- coding: utf-8 -*-
"""v3.64 visual check: 'כל המקבלים' header (#e2d81), RecipientDialog chip colour
(#m5bxy) and the redesigned Google card in settings (#vtf2f)."""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))

from shot import boot  # theme/RTL/font/temp-DB boot
import database as db
from PyQt6.QtCore import Qt, QPoint
from utils.ui import PRIORITY_BADGES

app, win = boot()

# ── seed: 3 regulars, 2 first-priority, 1 second, 1 "חובת בירור" ─────────────
seed = [
    ("כהן משה", 4, "4", "שבועי"), ("לוי דוד", 4, "4", "שבועי"), ("פרידמן יעקב", 4, "4", "חודשי"),
    ("אזולאי שרה", 3, "3", "חד-פעמי"), ("ביטון רחל", 3, "3", "חד-פעמי"),
    ("דהן אבי", 2, "2", "חד-פעמי"), ("מזרחי יוסף", None, "חובת בירור", ""),
]
for i, (nm, pr, raw, freq) in enumerate(seed):
    db.add_recipient({
        "full_name": nm, "phone1": f"05012345{i:02d}", "area": "הר יונה",
        "status": "פעיל" if i != 5 else "לא פעיל",
        "priority": pr, "priority_raw": raw, "frequency": freq,
        "children_total": 2 + i, "income": 4000 + i * 300, "marital_status": "נשוי",
    })
N_REG = sum(1 for s in seed if s[1] == 4)

keys = {t.objectName(): t for t in win._leaf_tabs}
tab = keys["tab_recipients"]

win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 880)
win.show()
app.processEvents(); app.processEvents()
from PyQt6.QtTest import QTest
def settle(ms=450):
    """_show_leaf fades the tab in (effects.fade_in, 170ms) — grabbing right
    after navigate captures a blank page, so let the animation finish."""
    QTest.qWait(ms)
    app.processEvents(); app.processEvents()
win.navigate_to_tab(tab)
tab.refresh()
settle()

out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)
win.grab().save(os.path.join(out, "recipients_v364.png"))
_pix = win.grab()
_dpr = _pix.devicePixelRatio()
_top = tab.mapTo(win, QPoint(0, 0)).y()
_pix.copy(0, int(_top * _dpr), _pix.width(), int(260 * _dpr)).save(os.path.join(out, "recipients_v364_head.png"))
print("shot: recipients_v364.png (+_head crop)")

# ── asserts: header row ──────────────────────────────────────────────────────
btns = [tab.btn_add, tab.btn_import, tab.btn_export, tab.btn_dup]
assert all(b.isVisible() for b in btns), "header button hidden"
title = next(w for w in tab.findChildren(type(tab.count_lbl)) if w.text() == "כל המקבלים")
def _y(w):
    return w.mapTo(tab, QPoint(0, 0)).y()
ty = _y(title)
for b in btns:
    assert abs(_y(b) + b.height() // 2 - (ty + title.height() // 2)) <= 18, ("button not in title row", b.text(), _y(b), ty)
assert "מקבלים" in tab.count_lbl.text(), tab.count_lbl.text()
assert tab.chip_regular.text().split()[0] == str(N_REG), (tab.chip_regular.text(), N_REG)
print("asserts ok: header row + chips", tab.count_lbl.text(), "|", tab.chip_active.text(), "|", tab.chip_regular.text())

# ── RecipientDialog for a priority-3 recipient: chip wears the badge colour ──
from tabs.recipients import RecipientDialog
rec = next(r for r in db.get_all_recipients() if r.get("priority") == 3)
dlg = RecipientDialog(tab, rec)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show()
settle(250)
bg, fg = PRIORITY_BADGES["ראשונה"]
qss = dlg.chip_state.styleSheet()
assert bg in qss and fg in qss, ("chip colour", qss)
dlg.grab().save(os.path.join(out, "recipient_dialog_v364.png"))
print("shot: recipient_dialog_v364.png | chip:", dlg.chip_state.text())
dlg.close()

# ── settings: Google card ────────────────────────────────────────────────────
stab = keys["tab_settings"]
win.navigate_to_tab(stab)
settle()
win.grab().save(os.path.join(out, "settings_google_v364.png"))
from PyQt6.QtWidgets import QScrollArea
_inner = stab.findChild(QScrollArea).widget()
_inner.grab().save(os.path.join(out, "settings_google_v364_fullpage.png"))
card = stab.google_state.parentWidget()
card.grab().save(os.path.join(out, "settings_google_card_v364.png"))
assert stab.lbl_google_status.text().strip(), "google status empty"
assert stab.btn_google_help.isVisible(), "help button hidden"
print("shot: settings_google_v364.png + card | status:", stab.lbl_google_status.text(),
      "| card size:", card.width(), "x", card.height())
print("done ->", out)
