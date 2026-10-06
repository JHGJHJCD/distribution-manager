# -*- coding: utf-8 -*-
"""משימה 8: PDF לדוגמה של כרטיס מקבל מודפס (בלי הדפסה פיזית) -> dev/_shots/card_print.pdf"""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
app, win = boot()
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtGui import QPageLayout
from PyQt6.QtCore import QMarginsF
from utils import print_view as pv

rec = {"full_name": "כהן יוסף", "phone1": "0501234567", "phone2": "0527654321", "id_number": "123456789",
       "spouse_id_number": "987654321", "address": "הרצל 12 נוף הגליל", "area": "מרכז", "souls": 7,
       "priority": 4, "frequency": "שבועי", "status": "פעיל", "holiday_support": 1,
       "last_distribution": "2026-09-30", "next_distribution": "2026-10-07",
       "notes": "משפחה גדולה, מעדיפים שיחה בבוקר"}
hist = [{"dist_date": f"2026-09-{30 - 7*i:02d}" if i < 4 else "2026-08-05", "what_dist": "סל מזון",
         "quantity": 1, "distributor": "רון", "notes": "קיבל" if i % 2 else ""} for i in range(8)]
pr = QPrinter(QPrinter.PrinterMode.HighResolution)
pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
pr.setPageOrientation(QPageLayout.Orientation.Portrait)
pr.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
out = os.path.join(REPO, "dev", "_shots", sys.argv[1] if len(sys.argv) > 1 else "card_print.pdf")
pr.setOutputFileName(out)
pv.render_recipient_card(pr, rec, hist) if hasattr(pv, "render_recipient_card") else None
print(out, os.path.exists(out) and os.path.getsize(out))
