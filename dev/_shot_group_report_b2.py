# -*- coding: utf-8 -*-
"""חבילה ב' ב8: שני הקיפולים פתוחים (מתקדמים + מתנדב), מצב ניקוד, רוחב 1280."""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
import database as db
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
app, win = boot()
for i in range(6):
    db.add_recipient({"full_name": f"לוי משפחה{i+1}", "phone1": f"05012345{i:02d}", "status": "פעיל",
                      "priority": 4, "frequency": "שבועי", "souls": 3 + i, "children_total": 2})
tab = {t.objectName(): t for t in win._leaf_tabs}["tab_dist"]
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1280, 1100); win.show(); app.processEvents(); win.navigate_to_tab(tab); QTest.qWait(400)
tab.products_spin.setValue(5)
tab.mode_combo.setCurrentIndex(tab.mode_combo.findData("scored"))
tab.adv_section.set_open(True); tab.vol_section.set_open(True)
for _ in range(6): app.processEvents()
QTest.qWait(300)
p = os.path.join(REPO, "dev", "_shots", "groupB_after2_1280_open.png"); win.grab().save(p); print(p)
