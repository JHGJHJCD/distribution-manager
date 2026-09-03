# -*- coding: utf-8 -*-
"""Grab the settings tab's inner scroll widget (clean render) to verify the new
'מספר מזוהה ביוצא' caller-id field in the yemot panel."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
              "..", ".claude", "skills", "visual-check", "scripts")))
from shot import boot, leaves
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea
import styles, database as db

app, win = boot()
keys = leaves(win)
settings = keys.get("tab_settings")
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 1600)
win.show()
win.navigate_to_tab(settings)
styles.apply_app_theme(app, db.get_ui_font_percent())
for _ in range(6):
    app.processEvents()

sa = settings.findChild(QScrollArea)
inner = sa.widget() if sa else settings
inner.resize(1340, inner.sizeHint().height())
for _ in range(4):
    app.processEvents()
out = os.path.join(os.path.dirname(__file__), "_shots", "yemot_caller.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
inner.grab().save(out)
print("shot:", out, inner.size())
