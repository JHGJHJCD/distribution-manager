# -*- coding: utf-8 -*-
"""משימה 10: כפתור "🗑 מחק" על כל שורת היסטוריה בחיפוש מהיר (חלון ראשי אמיתי, 1366x768).
צילום: dev/_shots/hist_delete_1366x768.png (לאמת דרך Gemini) + מדידת חיתוך הטקסט בעמודה."""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
app, win = boot()
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QFontMetrics
import database as db
import tabs.search as S

rid = db.add_recipient({
    "full_name": "כהן יוסף", "phone1": "0501234567", "id_number": "123456789",
    "address": "הרצל 12, נוף הגליל", "souls": 7, "priority": 4, "frequency": "שבועי",
    "status": "פעיל", "email": "yosef.cohen@example.com", "synagogue": "בית כנסת בעלז"})
rec = {"id": rid, "full_name": "כהן יוסף", "souls": 7}
for i in range(5):
    db.bulk_add_distributions([rec], f"2026-09-{30 - 7*i:02d}" if i < 4 else "2026-08-05",
                              "סל מזון", 1, "רון")
OUT = os.path.join(REPO, "dev", "_shots"); os.makedirs(OUT, exist_ok=True)
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1366, 768); win.show(); win.refresh_all()
win.navigate_to_tab(win.search_tab); QTest.qWait(450)
st = win.search_tab
st.search_input.setText("כהן"); st._run_search(); QTest.qWait(450)
ht = st.hist_table
col = S._HIST_DEL_COL
it = ht.item(0, col)
fm = QFontMetrics(it.font())
need = fm.horizontalAdvance(it.text())
print("viewport h:", ht.viewport().height(), "header h:", ht.horizontalHeader().height()); print("rows:", ht.rowCount(), "cols:", ht.columnCount(), "del col width:", ht.columnWidth(col),
      "text needs:", need, "hist table h:", ht.height(), "viewport w:", ht.viewport().width())
assert ht.columnWidth(col) >= need + 16, "delete text would be clipped"
# every column fits (no horizontal scrollbar), delete cell fully inside the viewport
assert ht.horizontalScrollBar().maximum() == 0, "horizontal scroll appeared"
r = ht.visualItemRect(it)
print("delete cell rect:", r.x(), r.y(), r.width(), r.height(), "viewport:", ht.viewport().width())
assert r.x() >= 0 and r.right() <= ht.viewport().width()
p = os.path.join(OUT, "hist_delete_1366x768.png")
for _ in range(4):
    win.grab().save(p)
    if os.path.getsize(p) > 40_000:
        break
    win.repaint(); QTest.qWait(100)
print(p, os.path.getsize(p))
# zoomed crop of just the history table
p2 = os.path.join(OUT, "hist_delete_table.png")
ht.grab().save(p2); print(p2, os.path.getsize(p2))
# geometry report (no image needed)
def top(w): return w.mapTo(st, w.rect().topLeft()).y()
for n, w_ in (("header", st.detail_header), ("details", st.detail_scroll), ("hist_title", st.hist_title),
              ("hist_table", ht), ("lbl_mails", st.lbl_mails), ("lbl_changes", st.lbl_changes)):
    print(f"  {n}: top={top(w_)} h={w_.height()} visible={w_.isVisible()}")
print("  tab h:", st.height(), "win:", win.width(), win.height(), "results_list w:", st.results_list.width())
print("  header cols:", [ht.columnWidth(c) for c in range(ht.columnCount())], "frame w:", ht.width())
# crop of the history area from the real window grab, 2x, for Gemini (taller window too)
from PyQt6.QtCore import QRect
def crop(name):
    full = win.grab()
    tl = ht.mapTo(win, ht.rect().topLeft())
    ttl = st.hist_title.mapTo(win, st.hist_title.rect().topLeft())
    d = full.devicePixelRatio()      # the grab is in device pixels (125%/150% screens)
    rc = QRect(int((tl.x() - 4) * d), int((ttl.y() - 4) * d), int((ht.width() + 8) * d),
               int(((tl.y() + ht.height()) - ttl.y() + 8) * d))
    img = full.copy(rc)
    pp = os.path.join(OUT, name); img.save(pp); print(pp, os.path.getsize(pp))
crop("hist_delete_crop_768.png")
win.resize(1366, 900); win.refresh_all(); QTest.qWait(450)
st.search_input.setText("כהן"); st._run_search(); QTest.qWait(450)
print("h900: hist h", ht.height(), "hbar", ht.horizontalScrollBar().maximum(), "vbar", ht.verticalScrollBar().maximum())
crop("hist_delete_crop_900.png")
# objective pixel check: red text pixels inside each delete cell (window grab at 900)
full = win.grab().toImage()
print("grab size", full.width(), full.height(), "dpr", full.devicePixelRatio())
vp = ht.viewport()
for r in range(min(ht.rowCount(), 5)):
    rr = ht.visualItemRect(ht.item(r, col))
    if rr.bottom() > vp.height():
        break
    tl = vp.mapTo(win, rr.topLeft())
    red = 0
    d = full.devicePixelRatio()
    for x in range(int(tl.x() * d), int((tl.x() + rr.width()) * d)):
        for y in range(int(tl.y() * d), int((tl.y() + rr.height()) * d)):
            c = full.pixelColor(x, y)
            if c.red() > 150 and c.green() < 90 and c.blue() < 90:
                red += 1
    print(f"  row {r}: delete cell {rr.width()}x{rr.height()} at win ({tl.x()},{tl.y()}) red_px={red}")
from collections import Counter
rr = ht.visualItemRect(ht.item(0, col)); tl = vp.mapTo(win, rr.topLeft()); d = full.devicePixelRatio()
cnt = Counter()
for x in range(int(tl.x() * d), int((tl.x() + rr.width()) * d)):
    for y in range(int(tl.y() * d), int((tl.y() + rr.height()) * d)):
        c = full.pixelColor(x, y); cnt[(c.red() // 16, c.green() // 16, c.blue() // 16)] += 1
print("colour buckets in cell 0:", cnt.most_common(6), "item fg:", ht.item(0, col).foreground().color().name())
