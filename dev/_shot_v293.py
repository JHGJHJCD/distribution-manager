# -*- coding: utf-8 -*-
"""צילומי אימות v2.93: (1) מובילים אוטומטיים במצב ניקוד + כפתור צהוב (#z7xq1,
#hwnwz); (2) שינוי מספר מוצרים מעדכן מובילים; (3) שם אוטומטי עברי (#o2eft);
(4) צינתוקים — מסך טעינה + אחרי טעינה + כפתור ייצוא היסטוריה (#ifc70, #67rdi)."""
import os, sys, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    "shot", os.path.join(REPO, ".claude", "skills", "visual-check", "scripts", "shot.py"))
shot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shot)

app, win = shot.boot()
import database as db

for i, (nm, inc) in enumerate([("כהן יוסף", "3000"), ("לוי שרה", "5000"),
                               ("אברהם דוד", "7000"), ("מזרחי חיים", "9000"),
                               ("פרץ רחל", "12000")]):
    db.add_recipient({"full_name": nm, "phone1": f"05{i}-123456{i}",
                      "status": "פעיל", "frequency": "שבועי", "priority": 4,
                      "souls": 3 + i, "income": inc, "children_total": str(2 + i)})
g = db.add_tzintuk_campaign("חלוקה של 26/08/2026", "2026-08-26", "1117319",
                            "camp-old", 5, device="מחשב המנהל")
db.update_tzintuk_campaign(g, 4, 1, "done")

from PyQt6.QtCore import Qt
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 950)
win.show()
app.processEvents(); app.processEvents()

out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)
gt = win.group_tab

# (3) שם אוטומטי עברי במצב שבועי רגיל
name = gt._effective_dist_name()
print("AUTO NAME:", repr(name))
app.processEvents()

# (1) מצב 'קבועים לפי ניקוד' עם 3 מוצרים → 3 מובילים מסומנים
idx = gt.mode_combo.findData("scored")
gt.mode_combo.setCurrentIndex(idx)
gt.products_spin.setValue(3)
for _ in range(8):
    app.processEvents()
gt.grab().save(os.path.join(out, "v293_scored_3.png"))
print("leaders@3:", sorted(gt._leader_ids))

# (2) שינוי ל-1 מוצר → מוביל אחד בלבד
gt.products_spin.setValue(1)
for _ in range(6):
    app.processEvents()
gt.grab().save(os.path.join(out, "v293_scored_1.png"))
print("leaders@1:", sorted(gt._leader_ids))

# חזרה למצב רגיל
gt.mode_combo.setCurrentIndex(gt.mode_combo.findData("schedule"))
for _ in range(4):
    app.processEvents()

# (4) צינתוקים — לפני ואחרי טעינה
from PyQt6.QtWidgets import QScrollArea
win.navigate_to_tab(win.tzintukim_tab)
win.tzintukim_tab.refresh()
for _ in range(6):
    app.processEvents()
tz_inner = win.tzintukim_tab.findChild(QScrollArea).widget()
tz_inner.grab().save(os.path.join(out, "v293_tz_unloaded.png"))
win.tzintukim_tab._load_week_list()
for _ in range(6):
    app.processEvents()
tz_inner.grab().save(os.path.join(out, "v293_tz_loaded.png"))
print("done")
