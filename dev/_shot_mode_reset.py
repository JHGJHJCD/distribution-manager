# -*- coding: utf-8 -*-
"""משימה 5: צילום קומבו מצב החלוקה — לפני 'הפעלה מחדש' (נבחר 'לפי ניקוד') ואחריה (חוזר ל'רגיל')."""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
import database as db
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

app, win1 = boot()
for i in range(4):
    db.add_recipient({"full_name": f"כהן קבוע{i}", "phone1": f"05012345{i:02d}", "status": "פעיל",
                      "priority": 4, "frequency": "שבועי", "children_total": 3})
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)


def snap(win, name):
    tab = {t.objectName(): t for t in win._leaf_tabs}["tab_dist"]
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(1360, 880); win.show(); app.processEvents()
    win.navigate_to_tab(tab); QTest.qWait(450)
    tab.adv_section.set_open(True)          # לראות את הקומבו גם כשהקיפול סגור
    for _ in range(8): app.processEvents()
    QTest.qWait(250)
    p = os.path.join(out, name + ".png")
    tab.adv_section.grab().save(p)
    print(name, "combo=", tab.mode_combo.currentText(), "| stored=", db.get_setting("dist_regulars_mode"),
          "| bytes=", os.path.getsize(p))


# הפעלה ראשונה: המשתמש בוחר 'לפי ניקוד'
tab1 = {t.objectName(): t for t in win1._leaf_tabs}["tab_dist"]
tab1.mode_combo.setCurrentIndex(tab1.mode_combo.findData("scored"))
snap(win1, "mode_reset_before")
win1.close()

# 'הפעלה מחדש' — חלון ראשי חדש על אותו DB
from main import MainWindow
win2 = MainWindow()
snap(win2, "mode_reset_after")
