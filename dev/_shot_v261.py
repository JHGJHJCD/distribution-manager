# -*- coding: utf-8 -*-
"""Visual audit of the v2.61 additions. Uses WA_DontShowOnScreen + grab() (the
project's Hebrew-safe capture path — offscreen renders squares)."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()
# Seed communities + a rep-less person
for i, (rep, inc, syn) in enumerate([("א", 1000, "המרכזי"), ("א", 9000, "המרכזי"),
                                     ("ב", 500, "המרכזי"), ("ב", 800, "הגדול"),
                                     ("ב", 2000, "הגדול"), ("ב", 9500, "הגדול")]):
    db.add_recipient({"full_name": f"משפחה {rep}{i}", "representative": f"נציג {rep}",
                      "income": str(inc), "children_total": 5, "synagogue": syn,
                      "status": "פעיל", "priority": 3 if i % 2 else 4,
                      "frequency": "חד-פעמי" if i % 2 else "שבועי",
                      "phone1": f"05000000{i}0", "area": "הר יונה"})
db.add_recipient({"full_name": "משפחה ללא נציג", "synagogue": "המרכזי", "status": "פעיל",
                  "income": "1200", "children_total": 4})
db.set_setting("available_products", "3")
db.set_filter_criteria({"income": {"min": None, "max": 3000}, "balance_communities": True})

app = QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
try:
    from qt_material import apply_stylesheet
    from styles import EXTRA_QSS, QT_MATERIAL_EXTRA
    apply_stylesheet(app, theme="light_teal.xml", invert_secondary=True, extra=QT_MATERIAL_EXTRA)
    app.setStyleSheet(app.styleSheet() + EXTRA_QSS)
except Exception:
    pass
app.setFont(QFont("Segoe UI", 11))

OUT = os.path.join(os.path.dirname(__file__), "shots_v261")
os.makedirs(OUT, exist_ok=True)


def shot(w, name, w_px=900, h_px=680):
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(w_px, h_px)
    w.show()
    app.processEvents()
    app.processEvents()
    w.grab().save(os.path.join(OUT, name + ".png"))
    print("shot:", name)


from tabs.group_update import (FilterCriteriaDialog, _ManualAddDialog,
                               CommunityAssignDialog)
from tabs.settings import CommunityQuotasDialog, SyncSetupDialog, SettingsTab
from tabs.distributions import DistributionsTab

shot(FilterCriteriaDialog(None, db.get_filter_criteria()), "01_filter_balance", 520, 460)
shot(_ManualAddDialog(None, set()), "02_manual_add", 820, 640)
shot(CommunityAssignDialog(None), "03_assign_communities", 620, 560)
shot(CommunityQuotasDialog(None), "04_community_quotas", 520, 560)
shot(SyncSetupDialog(None), "05_sync_setup", 620, 520)
shot(SettingsTab(None), "06_settings", 1200, 820)

print("DONE:", OUT)
