# -*- coding: utf-8 -*-
"""משימה 9: כרטיס הפרופיל בחיפוש מהיר — פרטים בשלוש עמודות, בלי גלילה.
assert-ים (גיאומטריה) + צילומים ל-dev/_shots/search_profile_*.png (לאמת דרך Gemini, לא Read)."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QFontMetrics
import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()
app = QApplication(sys.argv); app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
from styles import apply_app_theme
apply_app_theme(app, 100)
from tabs.search import SearchTab

OUT = os.path.join(os.path.dirname(__file__), "_shots"); os.makedirs(OUT, exist_ok=True)

FULL = {"full_name": "כהן יוסף", "phone1": "0501234567", "phone2": "0527654321", "phone3": "0541112223",
        "id_number": "123456789", "spouse_id_number": "987654321", "address": "הרצל 12, נוף הגליל",
        "area": "מרכז", "souls": 7, "priority": 4, "frequency": "שבועי", "status": "פעיל",
        "holiday_support": 1, "holidays": "פסח, סוכות, ראש השנה", "email": "yosef.cohen@example.com",
        "synagogue": "בית כנסת בעלז נוף הגליל",
        "notes": "משפחה גדולה, מעדיפים שיחה בבוקר. הילד הקטן חולה, לבדוק אם צריך עזרה נוספת לפני החג."}
rid = db.add_recipient(FULL)
rid_min = db.add_recipient({"full_name": "לוי משה", "phone1": "0502222222", "status": "פעיל"})
for i in range(3):   # 3 אי-הגעות רצופות -> באנר אזהרה
    db.bulk_add_distributions([], f"2026-09-{2 + 7*i:02d}", "סל מזון", 1, "רון",
                              not_received=[{"id": rid, "full_name": "כהן יוסף", "souls": 7}])
hist = db.get_distributions_for_recipient(rid)

tab = SearchTab()
tab.refresh(); app.processEvents()


def settle():
    for _ in range(6):
        app.processEvents()
    QTest.qWait(60)


def grab(w, name):
    p = os.path.join(OUT, name)
    for _ in range(4):
        w.grab().save(p)
        if os.path.getsize(p) > 40_000:
            return p
        app.processEvents(); w.repaint(); QTest.qWait(80)
    raise AssertionError(f"{name} too small: {os.path.getsize(p)}")


def metrics(label):
    sc = tab.detail_scroll
    card = tab.detail_card
    vbar = sc.verticalScrollBar()
    need = card.sizeHint().height()
    got = sc.viewport().height()
    print(f"[{label}] scroll w={sc.width()} scroll h={sc.height()} hfw={card.layout().totalHeightForWidth(sc.viewport().width())} card hint h={need} viewport h={got} vbar.max={vbar.maximum()} "
          f"vbar visible={vbar.isVisible()} cols={tab._detail_lay.columnCount()}")
    return need, got, vbar.maximum()


results = {}
for (w, h) in ((1366, 768), (1920, 1080), (1280, 720)):
    tab.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    tab.resize(w, h)
    tab.show(); settle()
    for key, r in (("full", rid), ("min", rid_min)):
        tab._show_recipient(r); settle()
        n, g, vm = metrics(f"{w}x{h} {key}")
        results[(w, h, key)] = (n, g, vm)
        grab(tab, f"search_profile_{key}_{w}x{h}.png")
print("OK", OUT)


# ── בדיקות גיאומטריה אובייקטיביות (לא תלויות בצילום) ─────────────────────────
def geometry_checks(w, h, key):
    from PyQt6.QtGui import QFontMetrics
    lay = tab._detail_lay
    caps, rows, spans = {}, [], []
    for i in range(lay.count()):
        r, c, rs, cs = lay.getItemPosition(i)
        wd = lay.itemAt(i).widget()
        if wd is None:
            continue
        x = wd.mapTo(tab.detail_card, wd.rect().topLeft()).x()
        if cs > 1:
            spans.append((r, wd))
        elif r == 0:
            caps[wd.findChild(QLabel).text() if wd.findChild(QLabel) else wd.text()
                 if isinstance(wd, QLabel) else "?"] = x
        else:
            rows.append((r, c, x, wd))
    return caps, rows, spans


tab.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
for (w, h) in ((1366, 768), (1100, 700), (1920, 1080)):
    tab.resize(w, h); tab.show(); settle()
    tab._show_recipient(rid); settle()
    caps, rows, spans = geometry_checks(w, h, "full")
    # סדר העמודות מימין לשמאל: קשר וכתובת > משפחה > חלוקות
    assert caps["קשר וכתובת"] > caps["משפחה"] > caps["חלוקות"], caps
    # שלוש עמודות בדיוק
    assert tab._detail_lay.columnCount() == 3
    # אין גלילה אנכית, ואין חיתוך של ערכים (לא עטופים-שורה: רוחב טקסט <= רוחב התווית)
    sc = tab.detail_scroll
    assert not sc.verticalScrollBar().isVisible() and sc.verticalScrollBar().maximum() == 0, \
        (w, h, sc.verticalScrollBar().maximum())
    clipped = []
    for r, c, x, wd in rows:
        vals = wd.findChildren(QLabel)
        val = vals[-1]
        fm = val.fontMetrics()
        f = val.font(); f.setBold(True)
        fm = QFontMetrics(f)
        need = fm.horizontalAdvance(val.text())
        if val.height() < fm.height() * 1.6 and need > val.width():     # שורה אחת וחתוך
            clipped.append((val.text(), need, val.width()))
    print(f"{w}x{h}: caps={caps}  scroll_h={sc.height()}  clipped_values={clipped}")
    # באנר ההערה/אזהרה במלוא הרוחב
    assert len(spans) == 2 and all(wd.width() >= tab.detail_card.width() - 40 for _, wd in spans), spans
    # הכרטיס לא חורג מעבר לרוחב הלשונית
    assert tab.detail_card.width() <= sc.viewport().width() + 1
    grab(tab, f"search_profile_geo_{w}x{h}.png")
print("GEOMETRY OK")


# ── כל ערך צמוד לתווית שלו (הצד הימני של תא הערך) — מדידת פיקסלים, לא ראייה ──────
def ink_right_gap(lbl):
    img = lbl.grab().toImage()
    right = -1
    for x in range(img.width() - 1, -1, -1):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            if c.alpha() > 0 and (c.red() + c.green() + c.blue()) < 450:   # כהה = טקסט
                right = x
                break
        if right >= 0:
            break
    return img.width() - 1 - right if right >= 0 else None


tab.resize(1366, 768); tab.show(); settle()
tab._show_recipient(rid); settle()
lay = tab._detail_lay
bad = []
for i in range(lay.count()):
    r, c, rs, cs = lay.getItemPosition(i)
    wd = lay.itemAt(i).widget()
    if wd is None or r == 0 or cs > 1:
        continue
    val = [l for l in wd.findChildren(QLabel) if l.text()][-1]
    gap = ink_right_gap(val)
    print("INK", val.text()[:24], "gap_to_right_edge=", gap, "of", val.width())
    if gap is None or gap > 14:
        bad.append((val.text(), gap, val.width()))
assert not bad, bad
print("VALUES HUG LABELS OK")
