# -*- coding: utf-8 -*-
"""משימה 9: כרטיס הפרופיל בתוך החלון הראשי האמיתי (חיפוש מהיר) בכמה גדלים.
צילומים: dev/_shots/search_main_<W>x<H>.png (לאמת דרך Gemini)."""
import os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
app, win = boot()
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
import database as db

rid = db.add_recipient({
    "full_name": "כהן יוסף", "phone1": "0501234567", "phone2": "0527654321", "id_number": "123456789",
    "spouse_id_number": "987654321", "address": "הרצל 12, נוף הגליל", "area": "מרכז", "souls": 7,
    "priority": 4, "frequency": "שבועי", "status": "פעיל", "holiday_support": 1,
    "email": "yosef.cohen@example.com", "synagogue": "בית כנסת בעלז",
    "notes": "משפחה גדולה, מעדיפים שיחה בבוקר"})
for i in range(6):
    db.bulk_add_distributions([{"id": rid, "full_name": "כהן יוסף", "souls": 7}],
                              f"2026-09-{30 - 7*i:02d}" if i < 4 else "2026-08-05",
                              "סל מזון", 1, "רון")
OUT = os.path.join(REPO, "dev", "_shots"); os.makedirs(OUT, exist_ok=True)
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
for (w, h) in ((1100, 700), (1366, 768), (1920, 1080)):
    win.resize(w, h); win.show()
    win.refresh_all()
    win.navigate_to_tab(win.search_tab)
    QTest.qWait(450)
    st = win.search_tab
    st.search_input.setText("כהן"); st._run_search(); QTest.qWait(450)
    sc = st.detail_scroll
    print(f"{w}x{h}: win={win.width()}x{win.height()} details_h={sc.height()} "
          f"vbar_max={sc.verticalScrollBar().maximum()} hist_h={st.hist_table.height()} "
          f"hist_rows_visible~{st.hist_table.viewport().height() // 30}")
    print("   scroll_needed_px=", sc.verticalScrollBar().maximum())
    p = os.path.join(OUT, f"search_main_{w}x{h}.png")
    for _ in range(4):
        win.grab().save(p)
        if os.path.getsize(p) > 40_000:
            break
        win.repaint(); QTest.qWait(100)
    print(p, os.path.getsize(p))


def layout_report():
    st = win.search_tab
    items = [("header", st.detail_header), ("details", st.detail_scroll), ("hist_title", st.hist_title),
             ("hist_table", st.hist_table), ("lbl_mails", st.lbl_mails), ("lbl_changes", st.lbl_changes)]
    out = []
    prev_bottom = None
    for n, w_ in items:
        top = w_.mapTo(st, w_.rect().topLeft()).y()
        out.append((n, top, w_.height(), w_.minimumSizeHint().height()))
        if prev_bottom is not None and top < prev_bottom - 1:
            out.append(("OVERLAP-with-previous", n, prev_bottom - top))
        prev_bottom = top + w_.height()
    return out


for (w, h) in ((1100, 700), (1366, 768), (1920, 1080)):
    win.resize(w, h); win.refresh_all(); QTest.qWait(450)
    print(w, h, layout_report())
# typical card: full fields, no notes, no no-show banner
rid2 = db.add_recipient({
    "full_name": "לוי דוד", "phone1": "0521112222", "id_number": "111222333", "spouse_id_number": "444555666",
    "address": "ויצמן 10, נוף הגליל", "area": "נתיב", "souls": 5, "priority": 4, "frequency": "שבועי",
    "status": "פעיל", "email": "d.levi@example.com", "synagogue": "בית כנסת ברסלב"})
for i in range(6):
    db.bulk_add_distributions([{"id": rid2, "full_name": "לוי דוד", "souls": 5}],
                              f"2026-09-{30 - 7*i:02d}" if i < 4 else "2026-08-05", "סל מזון", 1, "רון")
for (w, h) in ((1100, 700), (1366, 768), (1366, 900), (1920, 1080)):
    win.resize(w, h); win.refresh_all(); win.navigate_to_tab(win.search_tab); QTest.qWait(450)
    st.search_input.setText("לוי דוד"); st._run_search(); QTest.qWait(450)
    sc = st.detail_scroll
    print(f"TYPICAL {w}x{h}: tab_h={st.height()} details_h={sc.height()} want={sc._want_h} scroll_needed={sc.verticalScrollBar().maximum()} hist_h={st.hist_table.height()}")
    if (w, h) == (1366, 768):
        win.grab().save(os.path.join(OUT, "search_main_typical_1366x768.png"))
