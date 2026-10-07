# -*- coding: utf-8 -*-
"""דוח 7/10/2026 חבילה ב': צילומי מסך החלוקה (ריק / רשימה / מחסור / פח), בלי offscreen, DB זמני.
שימוש: python dev/_shot_group_report_b.py <תגית>"""
import os, sys
from datetime import timedelta
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
import database as db, selection
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
TAG = sys.argv[1] if len(sys.argv) > 1 else "after"
app, win = boot()
wed = selection.upcoming_wednesday()
for i in range(12):
    db.add_recipient({"full_name": f"כהן משפחה{i+1}", "phone1": f"05012345{i:02d}", "status": "פעיל",
                      "priority": 4, "frequency": "שבועי", "souls": 3 + i % 4, "children_total": 2 + i % 3,
                      "last_distribution": (wed - timedelta(days=7 * (2 + i))).isoformat()})
db.set_setting("dist_regulars_mode", "schedule")
tab = {t.objectName(): t for t in win._leaf_tabs}["tab_dist"]
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)
for W in (1280, 1920):
    win.resize(W, 1250); win.show(); app.processEvents()
    win.navigate_to_tab(tab); QTest.qWait(450)
    for name, products, reserve in (("empty", 0, 0), ("list", 20, 2), ("short", 8, 2)):
        tab.reserve_spin.setValue(reserve); tab.products_spin.setValue(products)
        for _ in range(6): app.processEvents()
        QTest.qWait(300)
        p = os.path.join(out, f"groupB_{TAG}_{W}_{name}.png")
        win.grab().save(p); print(p)
