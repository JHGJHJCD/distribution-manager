# -*- coding: utf-8 -*-
"""משימה 11: צילום כרטיס 'נשאר לחד-פעמיים' — אזהרה בלי כפתור / עודף עם כפתור."""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
import database as db
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

app, win = boot()
for i in range(15):
    db.add_recipient({"full_name": f"כהן קבוע{i}", "phone1": f"05012345{i:02d}", "status": "פעיל",
                      "priority": 4, "frequency": "שבועי", "children_total": 3})
db.set_setting("dist_regulars_mode", "schedule")
tab = {t.objectName(): t for t in win._leaf_tabs}["tab_dist"]
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 880); win.show(); app.processEvents()
win.navigate_to_tab(tab); QTest.qWait(450)
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)
for name, n in (("onetime_btn_low", 10), ("onetime_btn_high", 20)):
    tab.products_spin.setValue(n)
    tab._update_leftover_hint()
    for _ in range(6): app.processEvents()
    QTest.qWait(200)
    p = os.path.join(out, name + ".png")
    panel = tab.leftover_card.parentWidget()
    panel.grab().save(p)
    print(name, n, "card_visible=", not tab.leftover_card.isHidden(),
          "btn_visible=", not tab.btn_pick_onetime.isHidden(), tab.lbl_leftover.text(), os.path.getsize(p))

# משימה 12: הרמז לפי מספר הבחירות (20 מוצרים / 15 קבועים = 5 מקומות)
tab.products_spin.setValue(20)
for name, picks in (("onetime_hint_0", set()), ("onetime_hint_1of5", {990001}),
                    ("onetime_hint_5of5", {990001 + i for i in range(5)})):
    tab._extra_ids = picks; tab._reserve_ids = set()
    tab._update_leftover_hint()
    for _ in range(6): app.processEvents()
    QTest.qWait(200)
    p = os.path.join(out, name + ".png")
    tab.leftover_card.parentWidget().grab().save(p)
    print(name, len(picks), tab.lbl_leftover.text(), os.path.getsize(p))
