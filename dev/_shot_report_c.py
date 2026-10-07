# -*- coding: utf-8 -*-
"""חבילה ג' (דוח 7/10/2026): חיפוש מהיר בלי כותרת, פרטי חלוקה עם חיפוש, PDF רשימה עם/בלי תשובה, כרטיס."""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
app, win = boot()
import database as db
from datetime import timedelta
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)
ids = []
for i, nm in enumerate(["כהן יוסף", "לוי דוד", "מזרחי שרה", "אברהם משה", "כץ רחל"]):
    ids.append(db.add_recipient({"full_name": nm, "phone1": f"05010000{i}", "status": "פעיל"}))
w = db.next_wednesday()
for k in range(6):
    db.bulk_add_distributions([db.get_recipient(i) for i in ids[:4]], (w - timedelta(days=7 * (k + 1))).isoformat(),
                              "", "", "", dist_name=f"חלוקה {k+1}", general_note="")
b = db.get_distribution_batches()[0]
recs = db.get_batch_recipients(b["id"])
import sqlite3
_c = db.get_connection(); _c.execute("UPDATE distributions SET received=0 WHERE recipient_id IN (?,?) AND batch_id=?", (ids[2], ids[3], b["id"])); _c.commit()
win.show(); win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True); win.resize(1280, 800)
TS = [t for t in win._leaf_tabs if t.objectName()=="tab_search"][0]
win.navigate_to_tab(TS); QTest.qWait(500)
TS.search_input.setText("כהן"); TS._run_search(); QTest.qWait(500)
win.grab().save(os.path.join(out, "c_search.png"))
from tabs.distributions import BatchDetailsDialog
d = BatchDetailsDialog(b); d.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True); d.resize(520, 620); d.show()
app.processEvents(); app.processEvents()
d.grab().save(os.path.join(out, "c_dialog.png"))
d.search_edit.setText("לוי"); app.processEvents()
d.grab().save(os.path.join(out, "c_dialog_filtered.png"))
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtGui import QPageLayout
from PyQt6.QtCore import QMarginsF
from utils import print_view as pv
def pdf(name, rows):
    pr = QPrinter(QPrinter.PrinterMode.HighResolution); pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pr.setPageOrientation(QPageLayout.Orientation.Portrait); pr.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)
    p = os.path.join(out, name); pr.setOutputFileName(p)
    pv._make_dist_renderer(rows, pv._build_html(rows, "07/10/2026", False, "חלוקה לדוגמה"), False, "")(pr); print(p)
base = [{"full_name": n, "phone1": "0501234567", "area": "מרכז"} for n in ["כהן יוסף", "לוי דוד", "מזרחי שרה"]]
base.append({"full_name": "כץ רחל", "_reserve": True, "phone1": "0509999999"})
pdf("c_list_noans.pdf", base)
ans = [dict(r) for r in base]; ans[0]["_answer"] = "מגיע"; ans[1]["_confirmed"] = True
pdf("c_list_ans.pdf", ans)
rec = {"full_name": "כהן יוסף", "phone1": "0501234567", "id_number": "123456789", "address": "הרצל 12", "area": "מרכז",
       "souls": 7, "priority": 4, "frequency": "שבועי", "status": "פעיל", "notes": "הערה"}
hist = [{"dist_date": f"2026-09-{30 - 7*i:02d}", "what_dist": "סל", "quantity": 1, "distributor": "רון", "notes": ""} for i in range(4)]
pr = QPrinter(QPrinter.PrinterMode.HighResolution); pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
pr.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
pr.setOutputFileName(os.path.join(out, "c_card.pdf")); pv.render_recipient_card(pr, rec, hist)
os._exit(0)
