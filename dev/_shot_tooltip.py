# -*- coding: utf-8 -*-
"""צילום של הטולטיפ המעוצב מחדש — מרנדר את QToolTip האמיתי ותופס אותו.
הרצה: py312 dev/_shot_tooltip.py
"""
import os, sys
os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QWidget, QToolTip
from PyQt6.QtCore import QPoint, QTimer
import styles

app = QApplication.instance() or QApplication(sys.argv)
styles.apply_app_theme(app, 100)

# חלון-עוגן זעיר (לא מוצג באמת) רק כדי שתהיה נקודת-הצגה לטולטיפ
anchor = QWidget()
anchor.setFixedSize(10, 10)
anchor.show()

SHOTS = os.path.join(os.path.dirname(__file__), "_shots")
os.makedirs(SHOTS, exist_ok=True)

texts = [
    "שולח בדיקה אליי — ההודעה נשלחת לכתובת של חשבון הקופה",
    "כמה מנות יש בחלוקה · במצב רגיל הקבועים קודם, השאר לחד-פעמיים",
]

def capture():
    QToolTip.showText(QPoint(120, 120), texts[0])
    QTimer.singleShot(350, grab)

def grab():
    # מאתר את חלון הטולטיפ מבין החלונות העליונים ותופס אותו
    tip = None
    for w in app.topLevelWidgets():
        if w.metaObject().className() == "QTipLabel" and w.isVisible():
            tip = w
            break
    if tip is not None:
        pix = tip.grab()
        out = os.path.join(SHOTS, "tooltip_new.png")
        pix.save(out)
        print("SAVED", out, pix.width(), "x", pix.height())
    else:
        print("NO TIP WINDOW FOUND")
    app.quit()

QTimer.singleShot(150, capture)
app.exec()
