# -*- coding: utf-8 -*-
"""בדיקת #9hgvi: האם קליק ימני על טבלת החלוקות הקודמות פותח תפריט."""
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

db.add_recipient({"full_name": "כהן יוסף", "phone1": "052-1234567",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 5})
recs = db.get_all_recipients()
db.bulk_add_distributions([dict(r) for r in recs],
                          "2026-08-19", "", 1, "מחלק", dist_name="חלוקת בדיקה")

from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtWidgets import QMenu
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 950)
win.show()
app.processEvents(); app.processEvents()

dt = win.distributions_tab
win.navigate_to_tab(dt)
for _ in range(6):
    app.processEvents()

report = {}

orig_exec = QMenu.exec
def fake_exec(self, *a, **k):
    report["menu_opened"] = True
    report["actions"] = [act.text() for act in self.actions() if act.text()]
    return None
QMenu.exec = fake_exec

table = dt.table
# נקודה בתוך השורה הראשונה של ה-viewport
vp = table.viewport()
y = table.rowViewportPosition(0) + 5 if table.rowCount() else 5
pos = QPoint(30, y)
report["rows"] = table.rowCount()
report["rowAt(y)"] = table.rowAt(pos.y())
report["policy"] = str(table.contextMenuPolicy())

# מסלול 1: הסיגנל עצמו (מוודא שהחיבור עצמו תקין)
table.customContextMenuRequested.emit(pos)
report["via_signal"] = report.pop("menu_opened", False)
report["signal_actions"] = report.pop("actions", [])

# מסלול 2: אירוע קליק ימני אמיתי על ה-viewport (המסלול של המשתמש)
from PyQt6.QtGui import QContextMenuEvent
ev = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, vp.mapToGlobal(pos))
app.sendEvent(vp, ev)
app.processEvents()
report["via_event"] = report.pop("menu_opened", False)
report["event_actions"] = report.pop("actions", [])

QMenu.exec = orig_exec
import json
open(os.path.join(HERE, "_probe_ctxmenu_out.json"), "w", encoding="utf-8").write(
    json.dumps(report, ensure_ascii=False, indent=1))
print("done")
