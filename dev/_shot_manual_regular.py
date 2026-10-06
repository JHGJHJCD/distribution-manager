# -*- coding: utf-8 -*-
"""משימה 13: צילום רמז 'נשאר לחד-פעמיים' — 15 מוצרים, 10 קבועים שבועיים, ואחרי הוספה
ידנית של דו-שבועי שלא בתורו (נשאר 5 -> 4). בלי offscreen (עברית), DB זמני."""
import os, sys
from datetime import timedelta
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
import database as db
import selection
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

app, win = boot()
for i in range(10):
    db.add_recipient({"full_name": f"כהן קבוע{i}", "phone1": f"05012345{i:02d}", "status": "פעיל",
                      "priority": 4, "frequency": "שבועי", "children_total": 3})
db.add_recipient({"full_name": "לוי דו-שבועי", "phone1": "0521111119", "status": "פעיל",
                  "priority": 4, "frequency": "דו-שבועי", "children_total": 3,
                  "last_distribution": (selection.upcoming_wednesday() - timedelta(days=7)).isoformat()})
bi = [r for r in db.get_all_recipients() if r["full_name"] == "לוי דו-שבועי"][0]["id"]
db.set_setting("dist_regulars_mode", "schedule")
tab = {t.objectName(): t for t in win._leaf_tabs}["tab_dist"]
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 880); win.show(); app.processEvents()
win.navigate_to_tab(tab); QTest.qWait(450)
tab.products_spin.setValue(15)
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)
for name, extras in (("manual_regular_before", set()), ("manual_regular_after", {bi})):
    tab._extra_ids = set(extras); tab._reserve_ids = set(); tab._persist_extras()
    tab.refresh()
    for _ in range(6): app.processEvents()
    QTest.qWait(250)
    p = os.path.join(out, name + ".png")
    tab.leftover_card.parentWidget().grab().save(p)
    print(name, tab.lbl_leftover.text(), os.path.getsize(p))
