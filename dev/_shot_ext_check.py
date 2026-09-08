# -*- coding: utf-8 -*-
"""צילום חלון האזהרה של בדיקת שלוחה 76 (v3.34) — אותו טקסט/כפתורים כמו
TzintukimTab._callback_ext_ready, בלי DB ובלי רשת. אימות רק דרך gemini_task.py -f."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QTimer
import styles
from utils import callback_server as cbs

app = QApplication(sys.argv)
styles.apply_app_theme(app, 100)
problem = cbs.extension_problem("type=menu\napi_link=https://other.example.com")
box = QMessageBox()
box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
box.setIcon(QMessageBox.Icon.Warning)
box.setWindowTitle("צינתוקים")
box.setText(f"שלוחת המענה בקו לא תקינה:\n{problem}\n\n"
            "מי שיחזור לצינתוק לא ישמע את הודעת החלוקה ולא יוכל לאשר הגעה.\n"
            f"\"תקן ושלח\" כותב מחדש רק את שלוחה {cbs.EXT} (לא נוגע בשאר הקו).")
fix = box.addButton("תקן ושלח", QMessageBox.ButtonRole.AcceptRole)
skip = box.addButton("שלח בלי לתקן", QMessageBox.ButtonRole.DestructiveRole)
cancel = box.addButton("ביטול", QMessageBox.ButtonRole.RejectRole)
box.setDefaultButton(cancel)
box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
box.show()
out = os.path.join(os.path.dirname(__file__), "_shots", "ext_check_v334.png")
os.makedirs(os.path.dirname(out), exist_ok=True)

def grab():
    box.grab().save(out)
    print(out)
    app.quit()

QTimer.singleShot(400, grab)
app.exec()
