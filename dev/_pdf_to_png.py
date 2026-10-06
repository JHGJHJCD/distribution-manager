# -*- coding: utf-8 -*-
"""עזר: PDF -> PNG (עמוד ראשון, על רקע לבן) דרך QtPdf. שימוש: python dev/_pdf_to_png.py in.pdf out.png [רוחב]"""
import sys
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QColor
from PyQt6.QtPdf import QPdfDocument
app = QGuiApplication([])
d = QPdfDocument(None); d.load(sys.argv[1])
w = int(sys.argv[3]) if len(sys.argv) > 3 else 1240
sz = d.pagePointSize(0)
img = d.render(0, QSize(w, int(w * sz.height() / sz.width())))
out = QImage(img.size(), QImage.Format.Format_RGB32); out.fill(QColor("white"))
p = QPainter(out); p.drawImage(0, 0, img); p.end()
out.save(sys.argv[2]); print(sys.argv[2], out.width(), out.height())
