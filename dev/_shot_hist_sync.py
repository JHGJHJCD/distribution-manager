# -*- coding: utf-8 -*-
"""v3.10 — צילום כרטיס ההיסטוריה בלשונית הצינתוקים עם כפתור "היסטוריה מהשרת"
ותווית הידע על שעות המענה (מהמטמון האמיתי של המחשב)."""
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
g = db.add_tzintuk_campaign("חלוקת פרשת כי תבוא", "2026-09-02", "1430692",
                            "camp-old", 47, device="מחשב המנהל")
db.update_tzintuk_campaign(g, 44, 3, "done")

from PyQt6.QtCore import Qt
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 950)
win.show()
app.processEvents(); app.processEvents()
win.navigate_to_tab(win.tzintukim_tab)
tz = win.tzintukim_tab
tz.refresh()
for _ in range(6):
    app.processEvents()
out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)
card = tz.lbl_hist_sync.parentWidget()
while card is not None and card.width() < 600:
    card = card.parentWidget()
card.grab().save(os.path.join(out, "hist_sync_card.png"))
tz._scroll_body.ensureWidgetVisible(card) if hasattr(tz, "_scroll_body") else None
for _ in range(4): app.processEvents()
tz.grab().save(os.path.join(out, "hist_sync_tab.png"))
print("label:", tz.lbl_hist_sync.text())
print("done")
