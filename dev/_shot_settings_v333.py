# -*- coding: utf-8 -*-
"""צילום אימות לבלוק "שרת המענה" בכרטיס הצינתוקים בהגדרות (v3.33).
מאמתים רק דרך gemini_task.py -f (לא Read של ה-PNG — נטפרי)."""
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
db.set_setting(cb.SET_URL, cb.DEFAULT_URL); db.set_setting(cb.SET_SECRET, "demo-secret")
db.set_setting(cb.SET_ENABLED, "0")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 900); win.show()
for _ in range(4): app.processEvents()
win.navigate_to_tab(win.settings_tab)
st = win.settings_tab; st.refresh()
for _ in range(6): app.processEvents()
assert hasattr(st, "cb_url") and hasattr(st, "cb_secret") and hasattr(st, "cb_enabled")
# הטאב נבנה ב-boot() לפני שההגדרות נכתבו — ממלאים את השדות ישירות לצילום
st.cb_url.setText(cb.DEFAULT_URL); st.cb_secret.setText("demo-secret")
assert not st.cb_enabled.isChecked()
st.lbl_cb_status.setText("החיבור לשרת המענה תקין ✓ — 0 תשובות שמורות בשרת")
for _ in range(3): app.processEvents()
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)
inner = st.findChild(QScrollArea).widget()
inner.grab().save(os.path.join(out, "settings_v333_full.png"))
# חיתוך סביב הבלוק החדש — כדי שהאימות ב-Gemini יהיה ממוקד
from PyQt6.QtCore import QPoint
p = st.cb_url.mapTo(inner, QPoint(0, 0))
crop = inner.grab().copy(0, max(0, p.y() - 260), inner.width(), 420)
crop.save(os.path.join(out, "settings_v333_cb.png"))
print("done", inner.size(), "crop_y", p.y())
