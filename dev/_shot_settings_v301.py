# -*- coding: utf-8 -*-
"""צילום אימות למסך ההגדרות המעוצב מחדש (v3.01) — כל הדף הנגלל בתמונה אחת."""
import os, sys, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    "shot", os.path.join(REPO, ".claude", "skills", "visual-check", "scripts", "shot.py"))
shot = importlib.util.module_from_spec(spec); spec.loader.exec_module(shot)
app, win = shot.boot()
import database as db
db.set_setting("yemot_system", "0771234567"); db.set_setting("yemot_password", "1234")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 900); win.show()
for _ in range(4): app.processEvents()
win.navigate_to_tab(win.settings_tab)
st = win.settings_tab; st.refresh()
for _ in range(6): app.processEvents()
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)
st.grab().save(os.path.join(out, "settings_v301_top.png"))
inner = st.findChild(QScrollArea).widget()
inner.grab().save(os.path.join(out, "settings_v301_full.png"))
print("done", inner.size())
