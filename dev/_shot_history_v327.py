# -*- coding: utf-8 -*-
"""צילום אימות v3.27 — כרטיס היסטוריית הצינתוקים: רשומה שרצה (בלי "לא הגיבו"),
רשומה שהסתיימה (עם), ותזמון; ומעבר ל-100 רשומות (הטבלה גוללת, לא נחתכת)."""
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

ents = [{"phone": "0521111111", "name": "כהן יוסף", "status": "done", "ok": True, "failed": False},
        {"phone": "0522222222", "name": "לוי שרה", "status": "no_answer", "ok": False, "failed": True}]
yemot.merge_survey_answers(ents, [], "2026-09-06T08:00:00+00:00")
rj = json.dumps(ents, ensure_ascii=False)
g1 = db.add_tzintuk_campaign("חלוקת פרשת וילך — רץ עכשיו", "2026-09-09", "1117319", "c-live", 2,
                             sent_at="2026-09-07T07:10:00+00:00", device="מחשב המנהל")
db.update_tzintuk_campaign(g1, 1, 1, "sending", rj)
g2 = db.add_tzintuk_campaign("חלוקת פרשת נצבים", "2026-09-02", "1117319", "c-done", 2,
                             sent_at="2026-09-02T22:30:00+00:00", device="מחשב המנהל")
db.update_tzintuk_campaign(g2, 1, 1, "done", rj)
db.add_tzintuk_campaign("תזמון לרביעי", "2026-09-09", "900001", "s-1", 2,
                        sent_at="2026-09-09T10:00:00+00:00", status="scheduled")
for i in range(110):
    g = db.add_tzintuk_campaign(f"חלוקה ישנה {i + 1}", "2025-01-01", "1117319", f"old-{i}", 40,
                                sent_at=f"2025-{1 + i % 12:02d}-{1 + i % 28:02d}T10:00:00+00:00",
                                status="done")
    db.update_tzintuk_campaign(g, 38, 2, "done", rj)

from PyQt6.QtCore import Qt
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 950)
win.show()
app.processEvents(); app.processEvents()
out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)
win.navigate_to_tab(win.tzintukim_tab)
tz = win.tzintukim_tab
tz.refresh()
for _ in range(6):
    app.processEvents()
tz.hist.scrollToBottom()
n = tz.hist.rowCount()
last = tz.hist.item(n - 1, 1).text() if n else ""
tz.hist.scrollToTop()
for _ in range(4):
    app.processEvents()
tz.hist.grab().save(os.path.join(out, "history_v327.png"))
print("rows", n, "last", last, "sending-cell", tz.hist.item(0, 4).text() if n else "",
      "done-cell", tz.hist.item(2, 4).text() if n > 2 else "")
sb = tz.hist.verticalScrollBar()
print("scrollbar visible", sb.isVisible(), "max", sb.maximum(), "row2", tz.hist.item(1, 4).text())
