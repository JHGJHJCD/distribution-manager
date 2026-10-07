# -*- coding: utf-8 -*-
"""כלל 8 (7/10/2026): צילום מסך החלוקה במצב 'לפי לוח זמנים' כשיש 5 מוצרים ו-29
קבועים שבתור — הרשימה נחתכת ל-5 שמחכים הכי הרבה זמן + רזרבה. בלי offscreen, DB זמני."""
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
wed = selection.upcoming_wednesday()
FAM = ["כהן", "לוי", "מזרחי", "פרץ", "ביטון", "דהן", "אברהם", "פרידמן", "מלכה", "אזולאי"]
n = 0
for freq, count, weeks_ago in (("שבועי", 11, 2), ("דו-שבועי", 14, 2), ("דו-שבועי", 3, 6),
                               ("תלת-שבועי", 1, 6)):
    for i in range(count):
        db.add_recipient({"full_name": f"{FAM[n % 10]} משפחה{n + 1}", "phone1": f"05012345{n:02d}",
                          "status": "פעיל", "priority": 4, "frequency": freq, "souls": 3 + n % 5,
                          "last_distribution": (wed - timedelta(days=7 * weeks_ago)).isoformat()})
        n += 1
db.set_setting("dist_regulars_mode", "schedule")
db.set_setting("reserve_count", "5")
tab = {t.objectName(): t for t in win._leaf_tabs}["tab_dist"]
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 900); win.show(); app.processEvents()
win.navigate_to_tab(tab); QTest.qWait(450)
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)
for name, products in (("products_limit_5", 5), ("products_limit_29", 29)):
    tab.products_spin.setValue(products)
    for _ in range(6): app.processEvents()
    QTest.qWait(300)
    p = os.path.join(out, name + ".png")
    win.grab().save(p)
    tab.table.grab().save(os.path.join(out, name + "_table.png"))
    res = sum(1 for r in tab._rows_data if r.get("_reserve"))
    print(name, "| rows", len(tab._rows_data), "reserve", res, "|", tab.lbl_leftover.text(),
          "|", tab.lbl_regulars_count.text(), "|", os.path.getsize(p))
