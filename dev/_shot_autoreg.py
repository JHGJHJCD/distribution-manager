# -*- coding: utf-8 -*-
"""רישום אוטומטי של רשימה נעולה (19/10/2026, כלל 11): צילומי מסך — באנר הנעילה עם המתג, באנר
'נרשם אוטומטית' ומצב התיקון. בלי offscreen, DB זמני, שעון מדומה (חמישי 06:00).
לאמת את ה-PNG דרך gemini_task.py -f — לא Read (מלכודת נטפרי)."""
import os, sys
from datetime import datetime, timedelta
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
import database as db
import selection
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox

QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
app, win = boot()
import tabs.group_update as gu
wed = selection.upcoming_wednesday()
FAM = ["כהן", "לוי", "מזרחי", "פרץ", "ביטון", "דהן", "אברהם", "פרידמן", "מלכה", "אזולאי"]
n = 0
for freq, count, weeks_ago in (("שבועי", 8, 2), ("דו-שבועי", 3, 2), ("חודשי", 2, 5)):
    for i in range(count):
        db.add_recipient({"full_name": f"{FAM[n % 10]} משפחה{n + 1}", "phone1": f"05012345{n:02d}",
                          "status": "פעיל", "priority": 4, "frequency": freq, "souls": 3 + n % 5,
                          "last_distribution": (wed - timedelta(days=7 * weeks_ago)).isoformat()})
        n += 1
db.set_setting("dist_regulars_mode", "schedule")
db.set_setting("available_products", "13"); db.set_setting("reserve_count", "0")
tab = {t.objectName(): t for t in win._leaf_tabs}["tab_dist"]
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 900); win.show(); app.processEvents()
win.navigate_to_tab(tab); QTest.qWait(450)
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)


def shot(name, extra=""):
    for _ in range(6):
        app.processEvents()
    QTest.qWait(300)
    p = os.path.join(out, name + ".png")
    win.grab().save(p)
    print(name, os.path.getsize(p), "|", extra)


tab.dist_input.setCurrentText("רון")
tab.refresh()
tab._lock_plan()
shot("autoreg_1_lock_banner", tab.chk_plan_autoreg.text())
thu = datetime.combine(wed + timedelta(days=1), datetime.min.time()).replace(hour=6, minute=5)
res = tab.autoreg_tick(thu)
shot("autoreg_2_registered_banner", tab.lbl_autoreg.text())
auto = db.get_distribution_batches()[0]
gu.export_full_distribution_to_excel = lambda *a, **k: None
tab.start_autoreg_fix(auto)
for rid in list(tab._checked_ids)[:3]:
    tab._checked_ids.discard(rid)
tab._populate()
print("banner visible:", tab.stage_banner.isVisibleTo(tab))
tab._scroll_body.ensureWidgetVisible(tab.stage_banner, 0, 120)
shot("autoreg_3_fix_mode", tab.stage_banner.text())
print("done", len(res))
