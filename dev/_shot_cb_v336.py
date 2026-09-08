# -*- coding: utf-8 -*-
"""צילום אימות v3.36 — כרטיס הצינתוקים בהגדרות (כפתור "בדוק את שלוחת המענה בקו")
וכפתור "עדכן את שרת המענה" בכלי הרשימה של מסך הצינתוקים. DB זמני (shot.boot), בלי רשת.
אימות רק דרך gemini_task.py -f (לא Read)."""
import os, sys, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    "shot", os.path.join(REPO, ".claude", "skills", "visual-check", "scripts", "shot.py"))
shot = importlib.util.module_from_spec(spec); spec.loader.exec_module(shot)
app, win = shot.boot()
import database as db
from utils import callback_server as cb
db.set_setting("yemot_system", "0771234567"); db.set_setting("yemot_password", "1234")
db.set_setting(cb.SET_SECRET, "x"); db.set_setting(cb.SET_ENABLED, "1")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea, QPushButton
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 900); win.show()
for _ in range(4): app.processEvents()
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)

# settings: the callback-server block with both check buttons
win.navigate_to_tab(win.settings_tab)
st = win.settings_tab; st.refresh()
for _ in range(6): app.processEvents()
btn = next(b for b in st.findChildren(QPushButton) if b.text().startswith("בדוק את שלוחת המענה"))
card = btn.parentWidget()
while card is not None and card.width() < 500:
    card = card.parentWidget()
card.grab().save(os.path.join(out, "cb_v336_settings_card.png"))
assert st.lbl_cb_ext is not None and btn.isVisible()

# tzintukim: list tools row with the manual push button
tz = win.tzintukim_tab if hasattr(win, "tzintukim_tab") else next(
    t for t in win._leaf_tabs() if t.__class__.__name__ == "TzintukimTab")
win.navigate_to_tab(tz)
for _ in range(6): app.processEvents()
tz._load_week_list()                      # the tools row lives inside the list area
for _ in range(6): app.processEvents()
assert tz.btn_push_server.isVisible(), "push button hidden although server on"
row = tz.btn_push_server.parentWidget()
row.grab().save(os.path.join(out, "cb_v336_tz_tools.png"))
db.set_setting(cb.SET_ENABLED, "0"); tz.refresh()
for _ in range(3): app.processEvents()
assert not tz.btn_push_server.isVisible(), "push button visible although server off"
print("done")
