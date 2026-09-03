# -*- coding: utf-8 -*-
"""צילומי אימות לסקר אישור ההגעה (v3.02, שלוחה 77): טבלת הצינתוקים עם תשובות
1/2/3/לא-הגיב + רצועת המעקב + היסטוריה "תשובות בסקר"; תגי התשובה ב"חלוקה
ורישום"; כרטיס ההגדרות עם התוויות והשאלה. DB זמני בלבד."""
import os, sys, json, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    "shot", os.path.join(REPO, ".claude", "skills", "visual-check", "scripts", "shot.py"))
shot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shot)

app, win = shot.boot()
import database as db
from utils import yemot

for name, p1 in (("כהן יוסף", "052-1234567"), ("לוי שרה", "050-7654321"),
                 ("פרידמן משה", "04-6543210"), ("אברהם דוד", "053-1111111"),
                 ("מזרחי חיים", "054-2222222")):
    db.add_recipient({"full_name": name, "phone1": p1, "status": "פעיל",
                      "frequency": "שבועי", "priority": 4, "souls": 4})
db.set_setting("yemot_system", "0771234567")
db.set_setting("yemot_password", "1234")
db.set_setting("yemot_template_id", "1430692")

dist = db.next_wednesday().isoformat()
entries = [
    {"phone": "0521234567", "name": "כהן יוסף", "status": "done", "ok": True,
     "answer": "1", "answer_at": "2026-09-02T16:40:12+00:00"},
    {"phone": "0507654321", "name": "לוי שרה", "status": "done", "ok": True,
     "answer": "2", "answer_at": "2026-09-02T16:45:00+00:00"},
    {"phone": "046543210", "name": "פרידמן משה", "status": "no_answer", "failed": True,
     "answer": "3", "answer_at": "2026-09-02T17:00:00+00:00"},
    {"phone": "0531111111", "name": "אברהם דוד", "status": "done", "ok": True,
     "answer": "", "answer_at": ""},
    {"phone": "0542222222", "name": "מזרחי חיים", "status": "accepted", "ok": True,
     "confirmed": True},                      # דוח ישן (לפני הסקר)
]
g = db.add_tzintuk_campaign("חלוקת פרשת כי-תבוא", dist, "1430692", "camp-1", 5,
                            device="מחשב המנהל")
db.update_tzintuk_campaign(g, 4, 1, "done", json.dumps(entries, ensure_ascii=False))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 950)
win.show()
app.processEvents(); app.processEvents()
out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)

# 1. צינתוקים — רשימה טעונה עם תוצאות הסקר + רצועת מעקב שהסתיימה + היסטוריה
win.navigate_to_tab(win.tzintukim_tab)
tz = win.tzintukim_tab
tz.refresh()
tz._load_week_list()
tz._last_entries = list(entries)
tz._apply_results_to_table(entries, final=True)
tz.prog_frame.setVisible(True)
tz.lbl_prog.setText("הקמפיין הסתיים ✓ — 4 קיבלו את ההודעה, 1 נכשלו. "
                    "התשובות בסקר (הקשה 77) ממשיכות להתעדכן — כפתור \"רענן תשובות\" בהיסטוריה.")
tz.progress.setRange(0, 5); tz.progress.setValue(5)
tz.lbl_ans.setText(tz._answers_html(yemot.answer_counts(entries), final=True))
tz.lbl_done.setText("הצליחו 4"); tz.lbl_fail.setText("נכשלו 1"); tz.lbl_wait.setText("ממתינים 0")
tz._refresh_history()
for _ in range(6):
    app.processEvents()
tz.grab().save(os.path.join(out, "survey_tzintuk.png"))

# 2. חלוקה ורישום — תגי התשובה ליד השמות
gt = win.group_tab
win.navigate_to_tab(gt)
gt.refresh()
gt._populate()
for _ in range(6):
    app.processEvents()
gt.grab().save(os.path.join(out, "survey_dist.png"))
# הוכחה דטרמיניסטית (הטבלה עלולה להיות גלולה בצילום): טקסט + צבע רקע של תא השם
print("--- group tab name cells ---")
for r in range(gt.table.rowCount()):
    it = gt.table.item(r, 1)
    print(repr(it.text()), it.background().color().name())
print("--- tzintuk status cells ---")
for r in range(tz.table.rowCount()):
    it = tz.table.item(r, 3)
    print(repr(tz.table.item(r, 1).text() if tz.table.item(r, 1) else ""),
          "->", repr(it.text() if it else ""), it.foreground().color().name() if it else "")
gt.table.resize(1300, 420)
gt.table.grab().save(os.path.join(out, "survey_dist_table.png"))

# 3. הגדרות — כרטיס ימות עם התוויות והשאלה (הווידג'ט הפנימי של הגלילה)
st = win.settings_tab
win.navigate_to_tab(st)
st.refresh()
for _ in range(6):
    app.processEvents()
inner = st.findChild(QScrollArea).widget()
inner.grab().save(os.path.join(out, "survey_settings_full.png"))
print("done ->", out)
