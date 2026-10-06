"""Regression test (task 8): the printed recipient card has ruled tables and every
cell is right-aligned (Hebrew reader), like the printed distribution list.

Run:  python test_card_print.py   (Python 3.12, PYTHONUTF8=1)
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # geometry only, no glyph shapes

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSize, QMarginsF
from PyQt6.QtGui import QImage, QPainter, QColor, QPageLayout
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtPdf import QPdfDocument

app = QApplication.instance() or QApplication(sys.argv)

from utils import print_view as pv

_fail = 0


def check(name, cond):
    global _fail
    print(("  OK  " if cond else "  XX  ") + name)
    if not cond:
        _fail += 1


REC = {"full_name": "כהן & <בן> דוד", "phone1": "0501234567", "phone2": "0527654321",
       "id_number": "123456789", "spouse_id_number": "987654321",
       "address": "הרצל 12 נוף הגליל", "area": "מרכז", "souls": 7, "priority": 4,
       "frequency": "שבועי", "status": "פעיל", "last_distribution": "2026-09-30",
       "next_distribution": "2026-10-07", "notes": "ש & ב <b>הערה</b> ארוכה יותר מהשאר"}
HIST = [{"dist_date": "2026-09-30", "what_dist": "סל מזון & עוד", "quantity": 1,
         "distributor": "רון", "notes": "x"},
        {"dist_date": "2026-09-23", "what_dist": "סל", "quantity": 2,
         "distributor": "משה כהן", "notes": ""}]

# ── HTML level ──────────────────────────────────────────────────────────────
html = pv._card_html(REC, HIST, False)
check("T1 both card tables have visible borders", html.count("border='1'") >= 2)
check("T2 no centered cells in the card", "center" not in html.split("<body>")[1])
check("T3 values HTML-escaped exactly once",
      "&amp;" in html and "&amp;amp;" not in html and "<b>הערה" not in html)
check("T4 cells carry an RTL paragraph direction",
      "מס'" in html and html.count("dir='rtl'") >= 10)


# ── Rendered level: draw the card to a PDF, rasterise, measure ──────────────
def render_png() -> QImage:
    path = os.path.join(tempfile.gettempdir(), "test_card_print.pdf")
    pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pr.setPageOrientation(QPageLayout.Orientation.Portrait)
    pr.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    pr.setOutputFileName(path)
    pv.render_recipient_card(pr, REC, HIST)
    d = QPdfDocument(None)
    d.load(path)
    w = 1600
    sz = d.pagePointSize(0)
    img = d.render(0, QSize(w, int(w * sz.height() / sz.width())))
    out = QImage(img.size(), QImage.Format.Format_RGB32)
    out.fill(QColor("white"))
    p = QPainter(out)
    p.drawImage(0, 0, img)
    p.end()
    return out


im = render_png()
W, H = im.width(), im.height()


def is_line(c):          # the card's border colour #aaaacc
    return abs(c.red() - 0xAA) < 30 and abs(c.green() - 0xAA) < 30 and abs(c.blue() - 0xCC) < 30


def is_text(c):          # dark ink that is not the blue header band
    return c.lightness() < 120 and not (c.blue() > c.red() + 50)


def vlines(y0, y1):
    cols = [sum(1 for y in range(y0, y1, 2) if is_line(im.pixelColor(x, y))) for x in range(W)]
    mx = max(cols) if cols else 0
    xs = [x for x in range(W) if mx and cols[x] > mx * 0.5]
    groups = []
    for x in xs:
        if groups and x - groups[-1][-1] <= 3:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [sum(g) // len(g) for g in groups]


top = vlines(300, int(H * 0.45))        # details table region
check("T5 details table is ruled (left, middle and right vertical lines)", len(top) >= 3)

if len(top) >= 3:
    a, b = top[0], top[1]               # the value column (left of the label column)
    gaps = []
    y = 300
    while y < int(H * 0.45):
        if any(is_text(im.pixelColor(x, y)) for x in range(a + 10, b - 10, 3)):
            y0 = y
            while y < H and any(is_text(im.pixelColor(x, y)) for x in range(a + 10, b - 10, 3)):
                y += 1
            if y - y0 > 8:
                xs = [x for x in range(a + 8, b - 8) for yy in range(y0, y, 2)
                      if is_text(im.pixelColor(x, yy))]
                if xs and (max(xs) - min(xs)) < (b - a) * 0.8:     # skip full-width lines
                    gaps.append(b - max(xs))
        y += 1
    check("T6 details values measured (>=6 rows)", len(gaps) >= 6)
    med = sorted(gaps)[len(gaps) // 2] if gaps else 0
    same = [g for g in gaps if abs(g - med) <= 4]
    check("T7 details values hug the RIGHT edge of their cell (equal right gap)",
          len(same) >= 6)

hist_lines = vlines(int(H * 0.5), H - 100)
check("T8 history table is ruled (7 vertical lines)", len(hist_lines) >= 7)

print("FAILED" if _fail else "ALL OK", _fail)
sys.exit(1 if _fail else 0)
