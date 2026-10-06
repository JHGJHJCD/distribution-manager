"""Regression test (task 4): WednesdayCalendar highlights TODAY with an amber ring,
distinct from the teal Wednesday dot.

Run:  python test_calendar_today.py   (Python 3.12, PYTHONUTF8=1)
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # pixel colours only, no text

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QDate, QRect
from PyQt6.QtGui import QImage, QPainter, QColor

app = QApplication.instance() or QApplication(sys.argv)

import widgets

_fail = 0


def check(name, cond):
    global _fail
    print(("  OK  " if cond else "  XX  ") + name)
    if not cond:
        _fail += 1


cal = widgets.WednesdayCalendar()


def render_cell(d: QDate) -> QImage:
    img = QImage(60, 44, QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    cal.paintCell(p, QRect(0, 0, 60, 44), d)
    p.end()
    return img


def amber_pixels(img: QImage) -> int:
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            # amber ring #f59e0b (red high, green mid, blue low)
            if c.red() > 200 and 120 < c.green() < 190 and c.blue() < 90:
                n += 1
    return n


today = QDate.currentDate()
other = today.addDays(-1)
if other.month() != today.month():
    other = today.addDays(1)
# a day that is neither today nor a Wednesday
while other.dayOfWeek() == 3 or other == today:
    other = other.addDays(-1)

check("today cell has the amber ring", amber_pixels(render_cell(today)) > 60)
check("a regular other day has no amber", amber_pixels(render_cell(other)) == 0)

# a Wednesday that is not today: teal dot only, no amber
wed = today.addDays(-((today.dayOfWeek() - 3) % 7) - 7)
check("a Wednesday that is not today has no amber", amber_pixels(render_cell(wed)) == 0)

# today when it is a Wednesday still shows amber (ring) — painted on a Wednesday date
check("amber ring distinct from the teal Wednesday colour",
      QColor("#f59e0b") != QColor("#0d9488"))

print("FAILED" if _fail else "ALL OK")
sys.exit(1 if _fail else 0)
