# -*- coding: utf-8 -*-
"""Capture the redesigned 'חלוקה ורישום' tab (v3.03) in both stages, with data."""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))

from shot import boot  # reuse the exact theme/RTL/font/temp-DB boot
import database as db
from PyQt6.QtCore import Qt

app, win = boot()

# ── seed a handful of regulars due this week ─────────────────────────────────
names = ["כהן משה", "לוי דוד", "פרידמן יעקב", "אזולאי שרה", "ביטון רחל", "דהן אבי"]
for i, nm in enumerate(names):
    db.add_recipient({
        "full_name": nm,
        "phone1": f"05012345{i:02d}",
        "area": ["הר יונה", "נוף הגליל", "יזרעאליה"][i % 3],
        "status": "פעיל",
        "priority": 4,               # קבוע
        "frequency": "שבועי",
        "children_total": 3 + i,
        "income": 4000 + i * 500,
        "marital_status": "נשוי",
    })
db.set_setting("available_products", "4")
db.set_setting("reserve_count", "2")

keys = {t.objectName(): t for t in getattr(win, "_leaf_tabs", [])}
tab = keys["tab_dist"]

win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 880)
win.show()
app.processEvents(); app.processEvents()
win.navigate_to_tab(tab)
# scored mode lists ALL regulars by need (schedule mode shows only those DUE this
# week, which the freshly-seeded rows aren't) — so the shot actually has rows.
_i = tab.mode_combo.findData("scored")
if _i >= 0:
    tab.mode_combo.setCurrentIndex(_i)
tab.refresh()
app.processEvents(); app.processEvents()

out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)

# stage 1: prep
tab._set_stage("prep")
app.processEvents(); app.processEvents()
win.grab().save(os.path.join(out, "group_v303_prep.png"))
print("shot: group_v303_prep.png")

# stage 2: record — tick a couple so the summary/counts show
tab._set_stage("record")
app.processEvents(); app.processEvents()
rows = tab._visible_rows()
for rid in list(tab._checked_ids):
    pass
# tick the first two rows via their ids
ids = [r.get("id") for r in tab._rows_data if not r.get("_reserve")][:2]
tab._checked_ids.update(ids)
tab._populate()
app.processEvents(); app.processEvents()
win.grab().save(os.path.join(out, "group_v303_record.png"))
print("shot: group_v303_record.png")

# full-page grab of the scroll content (the tip in visual-check) so the whole
# list card + table are visible in one image, not clipped by the window height.
from PyQt6.QtWidgets import QScrollArea
inner = tab.findChild(QScrollArea).widget()
inner.grab().save(os.path.join(out, "group_v303_fullpage.png"))
print("shot: group_v303_fullpage.png")
print("done ->", out)
